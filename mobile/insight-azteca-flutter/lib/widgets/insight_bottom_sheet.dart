import 'package:flutter/material.dart';

import '../shared/extensions/build_context_x.dart';
import '../theme/radii.dart';
import '../theme/spacing.dart';

Future<T?> showInsightBottomSheet<T>({
  required BuildContext context,
  required WidgetBuilder builder,
  bool isScrollControlled = true,
}) {
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: isScrollControlled,
    useSafeArea: true,
    backgroundColor: Colors.transparent,
    barrierColor: Colors.black.withValues(alpha: 0.34),
    builder: builder,
  );
}

class InsightBottomSheet extends StatelessWidget {
  const InsightBottomSheet({
    super.key,
    required this.title,
    this.subtitle,
    this.trailing,
    required this.children,
    this.footer,
    this.maxHeightFactor = 0.86,
  });

  final String title;
  final String? subtitle;
  final Widget? trailing;
  final List<Widget> children;
  final Widget? footer;
  final double maxHeightFactor;

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.viewInsetsOf(context).bottom;
    final maxHeight = MediaQuery.sizeOf(context).height * maxHeightFactor;
    return AnimatedPadding(
      duration: const Duration(milliseconds: 180),
      curve: Curves.easeOutCubic,
      padding: EdgeInsets.only(bottom: bottomInset),
      child: Align(
        alignment: Alignment.bottomCenter,
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: maxHeight),
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: context.scheme.surface,
              borderRadius: const BorderRadius.vertical(top: InsightRadii.rXl),
              boxShadow: [
                BoxShadow(
                  color: Colors.black
                      .withValues(alpha: context.isDark ? 0.44 : 0.16),
                  blurRadius: 28,
                  offset: const Offset(0, -8),
                ),
              ],
            ),
            child: SafeArea(
              top: false,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const _SheetHandle(),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(
                      InsightSpacing.xl,
                      InsightSpacing.xs,
                      InsightSpacing.md,
                      InsightSpacing.md,
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                title,
                                style: context.tt.titleLarge?.copyWith(
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              if (subtitle != null) ...[
                                const SizedBox(height: InsightSpacing.xs2),
                                Text(
                                  subtitle!,
                                  style: context.tt.bodySmall
                                      ?.copyWith(color: context.ds.textLow),
                                ),
                              ],
                            ],
                          ),
                        ),
                        const SizedBox(width: InsightSpacing.sm),
                        // Ghosted circular close — a clearer affordance than a
                        // bare icon, aligned to the title's top edge.
                        trailing ??
                            Material(
                              color: context.ds.subtle,
                              shape: const CircleBorder(),
                              child: InkWell(
                                customBorder: const CircleBorder(),
                                onTap: () => Navigator.of(context).maybePop(),
                                child: Padding(
                                  padding: const EdgeInsets.all(7),
                                  child: Icon(
                                    Icons.close_rounded,
                                    size: 20,
                                    color: context.ds.textMid,
                                  ),
                                ),
                              ),
                            ),
                      ],
                    ),
                  ),
                  // Hairline under the header so the title block reads as a
                  // distinct section above the content list.
                  Divider(height: 1, thickness: 0.5, color: context.ds.divider),
                  const SizedBox(height: InsightSpacing.sm),
                  Flexible(
                    child: ListView(
                      shrinkWrap: true,
                      padding: const EdgeInsets.fromLTRB(
                        InsightSpacing.lg,
                        0,
                        InsightSpacing.lg,
                        InsightSpacing.lg,
                      ),
                      children: children,
                    ),
                  ),
                  if (footer != null)
                    DecoratedBox(
                      decoration: BoxDecoration(
                        border: Border(
                          top: BorderSide(color: context.ds.divider),
                        ),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.all(InsightSpacing.lg),
                        child: footer,
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class InsightSheetAction extends StatelessWidget {
  const InsightSheetAction({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle,
    required this.onTap,
    this.destructive = false,
  });

  final IconData icon;
  final String title;
  final String? subtitle;
  final VoidCallback onTap;
  final bool destructive;

  @override
  Widget build(BuildContext context) {
    final color = destructive ? context.ds.signal : context.ds.textHigh;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: InsightSpacing.xs),
      child: Material(
        color: context.ds.subtle,
        borderRadius: BorderRadius.circular(InsightRadii.md),
        child: ListTile(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(InsightRadii.md),
          ),
          leading: Icon(icon, color: color),
          title: Text(
            title,
            style: context.tt.bodyLarge?.copyWith(
              color: color,
              fontWeight: FontWeight.w600,
            ),
          ),
          subtitle: subtitle == null
              ? null
              : Text(
                  subtitle!,
                  style:
                      context.tt.bodySmall?.copyWith(color: context.ds.textLow),
                ),
          onTap: onTap,
        ),
      ),
    );
  }
}

class _SheetHandle extends StatelessWidget {
  const _SheetHandle();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(
        top: InsightSpacing.md,
        bottom: InsightSpacing.sm,
      ),
      child: Container(
        width: 44,
        height: 5,
        decoration: BoxDecoration(
          color: context.ds.textLow.withValues(alpha: 0.35),
          borderRadius: BorderRadius.circular(InsightRadii.pill),
        ),
      ),
    );
  }
}
