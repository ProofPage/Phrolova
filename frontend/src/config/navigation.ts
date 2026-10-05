import {
    BarChart3,
    Download,
    LayoutDashboard,
    MessageSquare,
    Radio,
    Settings,
    Terminal,
    type LucideIcon,
} from "lucide-react";

export interface NavItem {
    name: string;
    to: string;
    icon: LucideIcon;
}

export interface NavGroup {
    title: string;
    items: NavItem[];
}

/**
 * 사이드바와 커맨드 팔레트가 함께 읽는 화면 목록.
 *
 * 같은 목록을 두 곳에 복사해 두니 화면을 늘릴 때 팔레트 쪽을 빠뜨렸고
 * (System Logs가 없었다), 이름과 아이콘도 서로 어긋나 있었다
 * (Statistics/Stats, BarChart3/BarChart2).
 *
 * 라우터(App.tsx)는 경로를 페이지 컴포넌트에 잇는 다른 관심사라 합치지 않았다.
 * 여기에 페이지를 import하면 이 목록을 읽는 것만으로 전 화면이 딸려 온다.
 */
export const NAV_GROUPS: NavGroup[] = [
    {
        title: "모니터링",
        items: [{ name: "라이브 대시보드", to: "/", icon: LayoutDashboard }],
    },
    {
        title: "미디어 허브",
        items: [
            { name: "VOD 다운로드", to: "/vod", icon: Download },
            { name: "X Spaces 보관함", to: "/archive", icon: Radio },
            { name: "채팅 기록", to: "/chat", icon: MessageSquare },
        ],
    },
    {
        title: "워크스페이스",
        items: [
            { name: "통계", to: "/stats", icon: BarChart3 },
            { name: "시스템 로그", to: "/system-logs", icon: Terminal },
            { name: "설정", to: "/settings", icon: Settings },
        ],
    },
];

/** 그룹 구분 없이 펼친 목록 — 커맨드 팔레트처럼 순서만 필요한 곳에서 쓴다. */
export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((group) => group.items);
