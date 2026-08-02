import { redirect } from "next/navigation";

export default function DuplicateConsoleBasePathPage({
  params,
}: {
  params: { path?: string[] };
}) {
  const path = params.path?.join("/") || "operations";
  redirect(`/${path}`);
}
