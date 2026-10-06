import { useState, useEffect } from "react";
import { createBrowserRouter, RouterProvider, Outlet } from "react-router-dom";
import { Radio } from "lucide-react";
import { Layout } from "./components/layout/Layout";
import { ToastProvider } from "./components/ui/Toast";
import { ConfirmProvider } from "./components/ui/ConfirmModal";
import { SetupWizard } from "./components/SetupWizard";
import { ThemeProvider } from "./contexts/ThemeContext";
import { LanguageProvider, useLanguage } from "./contexts/LanguageContext";
import Dashboard from "./pages/Dashboard";
import VodDownload from "./pages/VodDownload";
import ArchivePage from "./pages/Archive";
import Settings from "./pages/Settings";
import ChatLogs from "./pages/ChatLogs";
import Stats from "./pages/Stats";
import SystemLogs from "./pages/SystemLogs";
import { Button } from "./components/ui/primitives";
import { CommandPalette } from "./components/ui/CommandPalette";

// Data Router 환경 안에서 렌더링되는 루트 레이아웃.
// SetupWizard 오버레이와 CommandPalette를 포함하며,
// 하위 라우트(<Layout />)는 <Outlet />으로 렌더링된다.
function RootLayout() {
    const { t } = useLanguage();
    // null은 "아직 확인 중" — 마법사를 깜빡 띄우지 않으려고 로딩 상태를 구분한다.
    const [needsSetup, setNeedsSetup] = useState<boolean | null>(null);
    const [setupDirectories, setSetupDirectories] = useState<{
        live_download_dir: string;
        vod_download_dir: string;
    } | null>(null);

    useEffect(() => {
        fetch("/api/setup/status")
            .then((r) => r.json())
            .then((data) => {
                setSetupDirectories(data.default_directories ?? null);
                setNeedsSetup(data.needs_setup);
            })
            .catch(() => setNeedsSetup(false));
    }, []);

    if (needsSetup === null) {
        return (
            <div className="app-canvas fixed inset-0 flex items-center justify-center">
                <div className="relative z-10 flex flex-col items-center">
                    <span className="brand-mark w-12 h-12 rounded-2xl grid place-items-center mb-4"><Radio className="w-5 h-5 animate-pulse" /></span>
                    <p className="text-sm font-semibold text-ink">Phrolova</p>
                    <p className="text-[11px] text-ink-faint mt-1">{t("워크스페이스를 준비하고 있습니다")}</p>
                </div>
            </div>
        );
    }

    return (
        <>
            {needsSetup && setupDirectories && (
                <SetupWizard
                    defaultDirectories={setupDirectories}
                    onComplete={() => setNeedsSetup(false)}
                />
            )}
            <CommandPalette />
            <Outlet />
        </>
    );
}

function RouteError() {
    const { t } = useLanguage();
    return <main className="app-canvas grid min-h-dvh place-items-center px-5">
        <div className="max-w-sm text-center"><h1 className="page-title">{t("화면을 표시하지 못했습니다.")}</h1><p className="page-description">{t("페이지를 새로고침하거나 라이브 화면으로 돌아가세요.")}</p><div className="mt-4 flex justify-center gap-2"><Button onClick={() => window.location.reload()}>{t("새로고침")}</Button><a className="ui-button btn-primary" href="/">{t("라이브로 이동")}</a></div></div>
    </main>;
}

const router = createBrowserRouter([
    {
        path: "/",
        element: <RootLayout />,
        errorElement: <RouteError />,
        children: [
            {
                element: <Layout />,
                children: [
                    { index: true, element: <Dashboard /> },
                    { path: "vod", element: <VodDownload /> },
                    { path: "archive", element: <ArchivePage /> },
                    { path: "chat", element: <ChatLogs /> },
                    { path: "stats", element: <Stats /> },
                    { path: "settings", element: <Settings /> },
                    { path: "system-logs", element: <SystemLogs /> },
                ],
            },
        ],
    },
]);

function App() {
    return (
        <LanguageProvider>
            <ThemeProvider>
                <ToastProvider>
                    <ConfirmProvider>
                        <RouterProvider router={router} />
                    </ConfirmProvider>
                </ToastProvider>
            </ThemeProvider>
        </LanguageProvider>
    );
}

export default App;
