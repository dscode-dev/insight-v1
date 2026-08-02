import 'package:flutter/material.dart';

import '../../../shared/extensions/build_context_x.dart';
import '../../../theme/spacing.dart';
import '../../../widgets/insight_segmented_control.dart';

/// Profile layout contract:
///
/// Header scrolls away with the page, the tab selector stays pinned, and the
/// selected section can change either by tapping a tab or swiping the content.
class ProfileTabsScaffold extends StatefulWidget {
  const ProfileTabsScaffold({
    super.key,
    required this.labels,
    required this.header,
    required this.children,
    this.initialIndex = 0,
    this.onIndexChanged,
  }) : assert(labels.length == children.length);

  final List<String> labels;
  final Widget header;
  final List<Widget> children;
  final int initialIndex;
  final ValueChanged<int>? onIndexChanged;

  @override
  State<ProfileTabsScaffold> createState() => _ProfileTabsScaffoldState();
}

class _ProfileTabsScaffoldState extends State<ProfileTabsScaffold>
    with SingleTickerProviderStateMixin {
  late TabController _controller;
  late int _selectedIndex;

  @override
  void initState() {
    super.initState();
    _selectedIndex = widget.initialIndex.clamp(0, widget.labels.length - 1);
    _controller = TabController(
      length: widget.labels.length,
      initialIndex: _selectedIndex,
      vsync: this,
    )..addListener(_handleControllerChanged);
  }

  @override
  void didUpdateWidget(covariant ProfileTabsScaffold oldWidget) {
    super.didUpdateWidget(oldWidget);
    final next = widget.initialIndex.clamp(0, widget.labels.length - 1);
    if (next != _selectedIndex && next != _controller.index) {
      _setSelected(next, animate: false);
    }
  }

  @override
  void dispose() {
    _controller
      ..removeListener(_handleControllerChanged)
      ..dispose();
    super.dispose();
  }

  void _handleControllerChanged() {
    if (_controller.indexIsChanging) return;
    final next = _controller.index;
    if (next == _selectedIndex) return;
    setState(() => _selectedIndex = next);
    widget.onIndexChanged?.call(next);
  }

  void _setSelected(int index, {bool animate = true}) {
    final next = index.clamp(0, widget.labels.length - 1);
    if (next == _selectedIndex && next == _controller.index) return;
    setState(() => _selectedIndex = next);
    widget.onIndexChanged?.call(next);
    if (animate) {
      _controller.animateTo(next);
    } else {
      _controller.index = next;
    }
  }

  @override
  Widget build(BuildContext context) {
    return NestedScrollView(
      headerSliverBuilder: (context, innerBoxIsScrolled) => [
        SliverToBoxAdapter(child: widget.header),
        SliverPersistentHeader(
          pinned: true,
          delegate: _ProfileTabsHeaderDelegate(
            child: _ProfileTabsBar(
              labels: widget.labels,
              selectedIndex: _selectedIndex,
              onChanged: _setSelected,
            ),
          ),
        ),
      ],
      body: TabBarView(
        controller: _controller,
        children: widget.children,
      ),
    );
  }
}

class _ProfileTabsBar extends StatelessWidget {
  const _ProfileTabsBar({
    required this.labels,
    required this.selectedIndex,
    required this.onChanged,
  });

  final List<String> labels;
  final int selectedIndex;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: context.ds.background,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          InsightSpacing.xl,
          InsightSpacing.sm,
          InsightSpacing.xl,
          InsightSpacing.sm,
        ),
        child: InsightSegmentedControl(
          labels: labels,
          selectedIndex: selectedIndex,
          onChanged: onChanged,
        ),
      ),
    );
  }
}

class _ProfileTabsHeaderDelegate extends SliverPersistentHeaderDelegate {
  const _ProfileTabsHeaderDelegate({required this.child});

  static const double _height = 54;
  final Widget child;

  @override
  double get minExtent => _height;

  @override
  double get maxExtent => _height;

  @override
  Widget build(
    BuildContext context,
    double shrinkOffset,
    bool overlapsContent,
  ) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: context.ds.background,
        boxShadow: overlapsContent
            ? [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.08),
                  blurRadius: 10,
                  offset: const Offset(0, 3),
                ),
              ]
            : null,
      ),
      child: child,
    );
  }

  @override
  bool shouldRebuild(covariant _ProfileTabsHeaderDelegate oldDelegate) =>
      child != oldDelegate.child;
}
