const configuredBasePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export const basePath =
  configuredBasePath === "/" ? "" : configuredBasePath.replace(/\/$/, "");

export function withBasePath(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (basePath && (normalizedPath === basePath || normalizedPath.startsWith(`${basePath}/`))) {
    return normalizedPath;
  }
  return `${basePath}${normalizedPath}`;
}

export function withoutBasePath(path: string): string {
  if (!basePath) return path;
  if (path === basePath) return "/";
  if (path.startsWith(`${basePath}/`)) return path.slice(basePath.length);
  return path;
}
