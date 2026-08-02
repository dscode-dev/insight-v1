import 'package:freezed_annotation/freezed_annotation.dart';

part 'user.freezed.dart';
part 'user.g.dart';

enum UserTier {
  @JsonValue('rookie')
  rookie,
  @JsonValue('scout')
  scout,
  @JsonValue('analyst')
  analyst,
  @JsonValue('oracle')
  oracle,
}

extension UserTierX on UserTier {
  String get labelPtBr {
    switch (this) {
      case UserTier.rookie:
        return 'Iniciante';
      case UserTier.scout:
        return 'Observador';
      case UserTier.analyst:
        return 'Analista';
      case UserTier.oracle:
        return 'Oráculo';
    }
  }
}

/// Compact profile of the currently-signed-in user.
@freezed
class CurrentUser with _$CurrentUser {
  const factory CurrentUser({
    required String id,
    required String username,
    required String displayName,
    required String initials,
    required String accentColor,
    int? reputation,
    UserTier? tier,
  }) = _CurrentUser;

  factory CurrentUser.fromJson(Map<String, dynamic> json) =>
      _$CurrentUserFromJson(json);
}
