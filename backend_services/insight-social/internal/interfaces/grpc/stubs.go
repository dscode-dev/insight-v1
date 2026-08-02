// Package grpc holds the gRPC server implementations for the 7
// social.v1 services declared in `insight-protos/proto/social/v1/`.
//
// W2.1b: all 7 aggregates are implemented in their own files:
//
//	user.go, community.go, discussion.go, signal.go, sentiment.go,
//	relationship.go, reputation.go
//
// This file used to host Unimplemented stubs during W2.0; it's
// retained as a single source of truth about the package layout.
package grpc
