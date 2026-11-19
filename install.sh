#!/usr/bin/env bash
# GNSS Caster — one-command installation and update from GitHub releases.
#
#   bash <(curl -Ls https://raw.githubusercontent.com/stepm65/GNSS-Caster/main/install.sh)
#   bash <(curl -Ls .../install.sh) v3.5.0         a specific release
#   bash <(curl -Ls .../install.sh) dev-latest     the installer from main (no checksum pinning)
#   bash <(curl -Ls .../install.sh) -- --status    pass a mode to gnss-caster-install.sh
#
# The release file gnss-caster-install.sh is verified against the SHA256SUMS
# published next to it, and against the version named by the tag, before it
# runs. On a fresh machine it runs "install"; when GNSS Caster is already
# installed it runs "--repair", the transactional update that stops the caster,
# keeps a snapshot and rolls back on a handled failure. Run it as root.
set -Eeuo pipefail
umask 077

REPO=stepm65/GNSS-Caster
RAW="https://raw.githubusercontent.com/$REPO/main/install.sh"
ASSET=gnss-caster-install.sh
SUMS=SHA256SUMS
INSTALLED_VERSION_FILE=/opt/gnss-caster/app/version.py
INSTALLED_UNIT=/etc/systemd/system/gnss-caster.service

say(){ printf '\n[GNSS Caster] %s\n' "$*"; }
die(){ printf '[GNSS Caster ERROR] %s\n' "$*" >&2; exit 1; }

usage(){
    cat <<EOF
GNSS Caster installer and updater

  bash <(curl -Ls $RAW)                   install or update to the latest release
  bash <(curl -Ls $RAW) v3.5.0            install or update to a specific release
  bash <(curl -Ls $RAW) dev-latest        installer from main, for test stands only
  ... --allow-downgrade                   allow installing an older version
  ... -- MODE [ARGS]                      run gnss-caster-install.sh MODE instead of
                                          the automatic install / --repair
                                          (for example: -- --status, -- --diagnose)

Before updating a working base station: finish field work, disconnect rovers
and keep a current backup. The caster stops while the update runs.
EOF
}

WORK=''
cleanup(){ [[ -z "$WORK" ]] || rm -rf -- "$WORK"; }

fetch(){  # url output max-seconds
    curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 \
         --retry 2 --connect-timeout 10 --max-time "$3" "$1" -o "$2"
}

valid_tag(){ [[ "$1" =~ ^v(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$ ]]; }

latest_release(){
    # Prints the newest published stable release tag, or nothing.
    local body tag=''
    body="$(curl --fail --silent --location --proto '=https' --connect-timeout 10 --max-time 20 \
              -H 'Accept: application/vnd.github+json' \
              "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null || :)"
    tag="$(printf '%s\n' "$body" | sed -nE 's/^[[:space:]]*"tag_name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' | head -n1)"
    if [[ -z "$tag" ]]; then
        # API rate limit or outage: the web redirect names the tag as well.
        tag="$(curl --silent --head --proto '=https' --connect-timeout 10 --max-time 20 -o /dev/null \
                 -w '%{redirect_url}' "https://github.com/$REPO/releases/latest" 2>/dev/null |
               sed -nE 's#.*/releases/tag/([^/?]+).*#\1#p' || :)"
    fi
    if valid_tag "$tag"; then printf '%s\n' "$tag"; fi
}

installer_version(){  # path -> X.Y.Z from "gnss-caster X.Y.Z"
    local line
    line="$(bash "$1" --version 2>/dev/null | head -n1 || :)"
    [[ "$line" =~ ^gnss-caster\ ([0-9]+\.[0-9]+\.[0-9]+)$ ]] || return 1
    printf '%s\n' "${BASH_REMATCH[1]}"
}

installed_version(){
    [[ -r "$INSTALLED_VERSION_FILE" ]] || return 0
    sed -nE 's/^__version__ = ["'"'"']([0-9]+\.[0-9]+\.[0-9]+)["'"'"']$/\1/p' "$INSTALLED_VERSION_FILE" | head -n1
}

version_older(){  # a b -> true when a < b
    [[ "$1" != "$2" && "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1)" == "$1" ]]
}

download_release(){  # tag dir -> verified dir/gnss-caster-install.sh
    local tag="$1" dir="$2" url version
    url="https://github.com/$REPO/releases/download/$tag"
    say "Downloading release $tag and its SHA256 sum"
    fetch "$url/$ASSET" "$dir/$ASSET" 300 || die "Release $tag or its installer was not found"
    fetch "$url/$SUMS" "$dir/$SUMS" 30 || die "SHA256SUMS for $tag is missing; refusing to install"
    [[ "$(wc -l < "$dir/$SUMS")" -eq 1 ]] || die 'Malformed SHA256SUMS: expected exactly one line'
    grep -Eq "^[0-9a-f]{64}  ${ASSET//./\\.}\$" "$dir/$SUMS" || die 'Unexpected SHA256SUMS format'
    (cd "$dir" && sha256sum --check --status "$SUMS") ||
        die 'SHA256 mismatch: the installer is damaged or was replaced. Nothing was installed.'
    say "SHA256 verified: $(cut -c1-16 "$dir/$SUMS")…"
    version="$(installer_version "$dir/$ASSET")" || die 'The downloaded installer does not report its version'
    [[ "v$version" == "$tag" ]] || die "Release $tag contains installer version $version; refusing to install"
}

download_main(){  # dir -> dir/gnss-caster-install.sh from main, unverified
    say 'Downloading the installer from main (not a release, no checksum pinning)'
    fetch "https://raw.githubusercontent.com/$REPO/main/$ASSET" "$1/$ASSET" 300 ||
        die 'Cannot download the installer from the main branch'
    installer_version "$1/$ASSET" >/dev/null || die 'The downloaded installer does not report its version'
}

main(){
    local target='' allow_downgrade=0 passthrough=0 arg
    local -a mode_args=()
    for arg in "$@"; do
        if ((passthrough)); then mode_args+=("$arg"); continue; fi
        case "$arg" in
            --) passthrough=1 ;;
            -h|--help) usage; return 0 ;;
            --allow-downgrade) allow_downgrade=1 ;;
            latest) target='' ;;
            dev-latest) target=dev-latest ;;
            v[0-9]*) valid_tag "$arg" || die "Invalid version '$arg': use a release tag such as v3.5.0"; target="$arg" ;;
            *) usage >&2; die "Unknown argument: $arg (installer modes go after --)" ;;
        esac
    done

    if [[ ${EUID} -ne 0 ]]; then
        cat >&2 <<EOF
[GNSS Caster ERROR] Root is required. Repeat the command as root:

  sudo bash -c "bash <(curl -Ls $RAW)${*:+ $*}"
EOF
        return 1
    fi
    local tool
    for tool in curl sha256sum sort sed grep; do
        command -v "$tool" >/dev/null 2>&1 || die "$tool is required (apt install $tool)"
    done

    if [[ -z "$target" ]]; then
        target="$(latest_release)"
        [[ -n "$target" ]] || die "No published release found in $REPO. Install a specific tag, or use dev-latest on a test stand."
    fi

    WORK="$(mktemp -d /var/tmp/gnss-caster-bootstrap.XXXXXXXX)"
    trap cleanup EXIT
    if [[ "$target" == dev-latest ]]; then
        download_main "$WORK"
    else
        download_release "$target" "$WORK"
    fi
    local wanted current
    wanted="$(installer_version "$WORK/$ASSET")"
    current="$(installed_version)"

    if ((${#mode_args[@]} == 0)); then
        if [[ -f "$INSTALLED_UNIT" || -n "$current" ]]; then
            if [[ -n "$current" ]] && version_older "$wanted" "$current" && ((allow_downgrade == 0)); then
                die "Installed version $current is newer than $wanted. Older code may not understand the current database. Add --allow-downgrade to do it anyway."
            fi
            mode_args=(--repair)
            say "Updating GNSS Caster${current:+ from $current} to $wanted with --repair."
            say 'The caster stops during the update; it is refused while rovers are connected or field work mode is on.'
        else
            mode_args=(install)
            say "Installing GNSS Caster $wanted"
        fi
    fi

    # The installer copies itself into /opt/gnss-caster, so it must run from a
    # real file. Give it the terminal for questions when there is one.
    local status=0
    if [[ -t 0 ]]; then
        bash "$WORK/$ASSET" "${mode_args[@]}" || status=$?
    elif { : </dev/tty; } 2>/dev/null; then
        bash "$WORK/$ASSET" "${mode_args[@]}" </dev/tty || status=$?
    else
        bash "$WORK/$ASSET" "${mode_args[@]}" </dev/null || status=$?
    fi
    if ((status != 0)); then
        die "gnss-caster-install.sh ${mode_args[*]} failed with exit code $status. See its messages above."
    fi
    say "Done: gnss-caster-install.sh ${mode_args[*]} ($wanted${target:+, $target})."
}

# Tests source this file with GNSS_CASTER_BOOTSTRAP_LIBRARY=1 to reach the
# functions without running the installation.
if [[ "${GNSS_CASTER_BOOTSTRAP_LIBRARY:-0}" != 1 ]]; then
    main "$@"
fi
