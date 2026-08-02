// Console navigation config (Console-X). Grouped into operator-meaningful
// sections. Shared by the server layout (permission filtering) and the client
// SidebarNav (rendering). Icons are lucide components.

import {
  Activity, AlertOctagon, ServerCog,
  Newspaper, BarChart3,
  Brain, BookOpen, Database, GitBranch, Server, Ticket,
  ScrollText, ShieldCheck, ShieldAlert,
  Users, UserCog, KeyRound,
  Gauge, Bot, FileText,
  MessageSquare, Boxes, Zap, Flag, Gavel,
} from "lucide-react";

import type { Permission } from "@/types/auth";

export type NavItem = {
  href: string;
  /** i18n key (navigation: `item.<key>`). English in `label` is the fallback. */
  key: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  permission: Permission;
};

export type NavGroup = { key: string; label: string; items: NavItem[] };

export const NAV_GROUPS: NavGroup[] = [
  {
    key: "operations",
    label: "Operations",
    items: [
      { href: "/operations", key: "operations", label: "Operations Center", icon: ServerCog, permission: "console.access" },
      { href: "/operations/history", key: "control-panel", label: "Control Panel", icon: Activity, permission: "console.access" },
      { href: "/dlq", key: "dlq", label: "Dead Letter Queue", icon: AlertOctagon, permission: "dlq.read" },
    ],
  },
  {
    key: "intelligence",
    label: "Intelligence",
    items: [
      { href: "/atlas/intelligence", key: "atlas-intelligence", label: "Atlas Intelligence", icon: Brain, permission: "console.access" },
      { href: "/atlas/knowledge", key: "atlas-knowledge", label: "Atlas Knowledge", icon: BookOpen, permission: "console.access" },
    ],
  },
  {
    key: "data",
    label: "Data",
    items: [
      { href: "/data-intelligence/pipelines", key: "mission-center", label: "Mission Center", icon: GitBranch, permission: "console.access" },
      { href: "/data-intelligence/datasets", key: "dataset-center", label: "Dataset Center", icon: Database, permission: "console.access" },
      { href: "/data-intelligence/sources", key: "sources", label: "Sources", icon: Server, permission: "console.access" },
      { href: "/data-intelligence/tickets", key: "tickets", label: "Tickets", icon: Ticket, permission: "console.access" },
    ],
  },
  {
    key: "realtime",
    label: "Realtime",
    items: [
      { href: "/publication-center", key: "publication-center", label: "Publication Center", icon: Newspaper, permission: "console.access" },
      { href: "/analytics/publications", key: "publication-analytics", label: "Publication Analytics", icon: BarChart3, permission: "console.access" },
      { href: "/moderation", key: "moderation", label: "Moderation Center", icon: ShieldAlert, permission: "feed.read" },
    ],
  },
  {
    key: "social",
    label: "Social",
    items: [
      { href: "/social", key: "social-overview", label: "Overview", icon: Gauge, permission: "feed.read" },
      { href: "/social/activity", key: "social-activity", label: "Activity", icon: Activity, permission: "feed.read" },
      { href: "/social/posts", key: "social-posts", label: "Posts", icon: FileText, permission: "feed.read" },
      { href: "/social/comments", key: "social-comments", label: "Comments", icon: MessageSquare, permission: "feed.read" },
      { href: "/social/users", key: "social-users", label: "Users", icon: Users, permission: "user.read" },
      { href: "/social/agents", key: "social-agents", label: "Agents", icon: Bot, permission: "user.read" },
      { href: "/social/communities", key: "social-communities", label: "Communities", icon: Boxes, permission: "feed.read" },
      { href: "/social/boosts", key: "social-boosts", label: "Boosts", icon: Zap, permission: "feed.read" },
      { href: "/social/reports", key: "social-reports", label: "Reports", icon: Flag, permission: "feed.read" },
      { href: "/social/moderation", key: "social-moderation", label: "Moderation", icon: Gavel, permission: "feed.read" },
    ],
  },
  {
    key: "administration",
    label: "Administration",
    items: [
      { href: "/auth", key: "authentication", label: "Authentication", icon: ShieldCheck, permission: "console.access" },
      { href: "/audit", key: "audit", label: "Audit Center", icon: ScrollText, permission: "audit.read" },
      { href: "/administration/users", key: "users", label: "Users", icon: Users, permission: "console.access" },
      { href: "/administration/operators", key: "operators", label: "Operators", icon: UserCog, permission: "console.access" },
      { href: "/administration/sessions", key: "sessions", label: "Sessions", icon: KeyRound, permission: "console.access" },
    ],
  },
];
