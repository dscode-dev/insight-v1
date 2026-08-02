import 'package:flutter/material.dart';

import '../../../models/feed.dart';
import '../../../shared/extensions/build_context_x.dart';

class ReplyPreviewView extends StatelessWidget {
  const ReplyPreviewView({super.key, required this.data, this.onTap});

  final FeedReplyPreview data;
  final VoidCallback? onTap;

  String _cta() {
    if (data.count == 1) return 'Ver 1 resposta';
    return 'Ver ${data.count} respostas';
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (data.preview != null)
                Text.rich(
                  TextSpan(
                    style: context.tt.bodySmall
                        ?.copyWith(color: context.ds.textMid),
                    children: [
                      TextSpan(
                        text: data.preview!.authorDisplayName,
                        style: TextStyle(color: context.ds.textHigh),
                      ),
                      const TextSpan(text: ' · '),
                      TextSpan(text: data.preview!.text),
                    ],
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              Text(
                _cta(),
                style: context.tt.labelSmall?.copyWith(color: context.ds.signal),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
