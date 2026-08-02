import 'package:flutter/material.dart';

import '../../../models/hub.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../theme/radii.dart';
import '../../../widgets/avatar.dart';

class TipsterTile extends StatelessWidget {
  const TipsterTile({super.key, required this.tipster});
  final Tipster tipster;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 180,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: context.ds.card,
        borderRadius: InsightRadii.brLg,
        border: Border.all(color: context.ds.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              InsightAvatar(
                initials: tipster.initials,
                colorHex: tipster.accentColor,
                size: 36,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      tipster.displayName,
                      style: context.tt.titleMedium,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text(
                      tipster.tier,
                      style: context.tt.labelSmall
                          ?.copyWith(color: context.ds.textLow),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Text(
                '${(tipster.accuracy * 100).round()}%',
                style: context.tt.titleMedium?.copyWith(
                  color: context.ds.confidenceHigh,
                  fontFeatures: const [FontFeature.tabularFigures()],
                ),
              ),
              const SizedBox(width: 6),
              Text(
                'precisão',
                style: context.tt.labelSmall
                    ?.copyWith(color: context.ds.textLow),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Text(
            '${tipster.signals} sinais',
            style: context.tt.labelSmall
                ?.copyWith(color: context.ds.textMid),
          ),
        ],
      ),
    );
  }
}
