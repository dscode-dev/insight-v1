// GET /api/v1/reminders  — the list
// POST /api/v1/reminders — create a declared reminder
//
// A catch-all segment needs at least one path segment, so the collection
// itself cannot live in `[...path]`. Both files delegate to the same
// handlers in ./handlers so there is one place where permission, audit
// and the upstream path are decided.
export { GET, POST } from "./handlers";
