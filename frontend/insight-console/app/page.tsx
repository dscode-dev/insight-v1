import { redirect } from "next/navigation";

export default function Index() {
  // Middleware handles unauthenticated → /login. Authenticated users
  // land on the operational command center.
  redirect("/operations");
}
