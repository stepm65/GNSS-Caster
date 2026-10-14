import { createContext } from "react";
export const Session = createContext({
  role: "viewer",
  canEdit: false,
  isAdmin: false,
});
