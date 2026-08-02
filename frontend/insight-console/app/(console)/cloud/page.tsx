import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default function CloudPage() {
  redirect("/operations");
}
