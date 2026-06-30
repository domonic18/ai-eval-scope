/**
 * Icon shim（迁移期）—— 把原自研 IconXxx 重导出为 lucide-react 组件，
 * 保留原命名与 {size} 调用方式，调用点零改动。
 * lucide 原生支持 size / className / strokeWidth；迁移完成后直接用 lucide。
 */
export {
  LayoutDashboard as IconDashboard,
  Activity as IconRuns,
  Users as IconMembers,
  Settings as IconSettings,
  Search as IconSearch,
  Bell as IconBell,
  Plus as IconPlus,
  RefreshCw as IconRefresh,
  ChevronDown as IconChevronDown,
  ChevronDown as IconCaret,
  ExternalLink as IconExternal,
  Download as IconDownload,
  Mail as IconMail,
  Lock as IconLock,
  HelpCircle as IconHelp,
  Trash2 as IconTrash,
  TriangleAlert as IconWarn,
  Info as IconInfo,
  ArrowRight as IconArrowRight,
  ArrowLeft as IconArrowLeft,
  FileText as IconFile,
  Eye as IconEye,
  X as IconClose,
  LogOut as IconLogout,
  Copy as IconCopy,
  BookOpen as IconBook,
  KeyRound as IconKey,
} from "lucide-react"
