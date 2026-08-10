// POST /api/v1/reminders/{slug}/{done|mute|observed}
//
// Same handlers as the collection route one level up — see ../handlers
// for why muting is the only action that carries the audit spine.
export { GET, POST } from "../handlers";
