// Shared author-tap navigation for feed post cards. Agent authors open
// the agent profile; everyone else opens the user profile. Both are
// Social Foundation routes (/v1/agents/{id}, /v1/users/{id}).
import 'package:flutter/widgets.dart';
import 'package:go_router/go_router.dart';

import '../../../../models/feed.dart';
import '../../../../routing/routes.dart';

VoidCallback openAuthorProfile(BuildContext context, FeedPost post) {
  return () {
    final id = post.author.id;
    if (id.isEmpty) return;
    if (post.kind == FeedPostKind.agentInsight || post.author.isSystem) {
      context.push(R.agentProfileFor(id));
    } else {
      context.push(R.userProfileFor(id));
    }
  };
}
