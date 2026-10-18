import type { ComponentType } from 'react'
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined'
import LibraryBooksOutlinedIcon from '@mui/icons-material/LibraryBooksOutlined'
import AccountTreeOutlinedIcon from '@mui/icons-material/AccountTreeOutlined'
import ArticleOutlinedIcon from '@mui/icons-material/ArticleOutlined'
import QuizOutlinedIcon from '@mui/icons-material/QuizOutlined'
import FormatListBulletedOutlinedIcon from '@mui/icons-material/FormatListBulletedOutlined'
import PlayCircleOutlineOutlinedIcon from '@mui/icons-material/PlayCircleOutlineOutlined'
import InsightsOutlinedIcon from '@mui/icons-material/InsightsOutlined'
import GridOnOutlinedIcon from '@mui/icons-material/GridOnOutlined'
import SwapHorizOutlinedIcon from '@mui/icons-material/SwapHorizOutlined'
import TimelineOutlinedIcon from '@mui/icons-material/TimelineOutlined'
import BoltOutlinedIcon from '@mui/icons-material/BoltOutlined'
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined'

/**
 * The navigation table — one list, two consumers.
 *
 * The sidebar renders it and the route table will be written against it, so a
 * view cannot exist in one place and be missing from the other. That drift is
 * the classic multi-view failure: a page nobody can reach, or a link to a page
 * that does not exist.
 *
 * Groups are ordered as the mock approved them: the student's work, the
 * instructor's analytics, then the machinery.
 */
export type NavGroup = 'Student' | 'Faculty' | 'System'

export interface NavItem {
  group: NavGroup
  label: string
  to: string
  icon: ComponentType<{ fontSize?: 'inherit' | 'small' | 'medium' | 'large' }>
}

export const NAV_GROUPS: NavGroup[] = ['Student', 'Faculty', 'System']

export const NAV: NavItem[] = [
  // Student — do the work
  { group: 'Student', label: 'Overview', to: '/student/overview', icon: DashboardOutlinedIcon },
  { group: 'Student', label: 'Lectures', to: '/student/lectures', icon: LibraryBooksOutlinedIcon },
  { group: 'Student', label: 'Concept map', to: '/student/map', icon: AccountTreeOutlinedIcon },
  { group: 'Student', label: 'Lecture detail', to: '/student/lecture', icon: ArticleOutlinedIcon },
  { group: 'Student', label: 'Quiz', to: '/student/quiz', icon: QuizOutlinedIcon },
  {
    group: 'Student',
    label: 'Remediation',
    to: '/student/remediation',
    icon: FormatListBulletedOutlinedIcon,
  },
  { group: 'Student', label: 'Clips', to: '/student/clips', icon: PlayCircleOutlineOutlinedIcon },

  // Faculty — see the learning
  { group: 'Faculty', label: 'Analytics', to: '/faculty/analytics', icon: InsightsOutlinedIcon },
  { group: 'Faculty', label: 'Heatmap', to: '/faculty/heatmap', icon: GridOnOutlinedIcon },
  { group: 'Faculty', label: 'Divergence', to: '/faculty/divergence', icon: SwapHorizOutlinedIcon },
  { group: 'Faculty', label: 'Coverage', to: '/faculty/coverage', icon: TimelineOutlinedIcon },

  // System
  { group: 'System', label: 'Jobs', to: '/jobs', icon: BoltOutlinedIcon },
  { group: 'System', label: 'System & quota', to: '/system', icon: TuneOutlinedIcon },
]
