package community

import "errors"

var (
	ErrNotFound           = errors.New("community: not found")
	ErrSlugTaken          = errors.New("community: slug already taken")
	ErrInvalidSlug        = errors.New("community: invalid slug")
	ErrInvalidName        = errors.New("community: invalid name")
	ErrInvalidTopic       = errors.New("community: invalid topic")
	ErrInvalidAccentColor = errors.New("community: invalid accent color")
	ErrAlreadyMember      = errors.New("community: user already a member")
	ErrNotMember          = errors.New("community: user not a member")

	// FEATURE-COMMUNITIES-V1 — ownership + role invariants.
	ErrOwnerRequired       = errors.New("community: owner_user_id is required for a new community")
	ErrOwnerCannotLeave    = errors.New("community: owner cannot leave without transferring ownership")
	ErrOwnerImmutable      = errors.New("community: the owner cannot be removed or demoted by this operation")
	ErrOwnerExists         = errors.New("community: community already has an owner")
	ErrRoleChangeDenied    = errors.New("community: actor is not authorized to make this role change")
	ErrCannotAssignOwner   = errors.New("community: ownership can only change via an explicit transfer")
	ErrTransferUnsupported = errors.New("community: ownership transfer is not available in V1")

	ErrInvalidMembersCursor = errors.New("community: invalid members cursor")
)
