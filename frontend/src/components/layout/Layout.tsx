import { Outlet } from "react-router-dom";
import { Topbar } from "./Topbar";
import { Sidebar } from "./Sidebar";
import { VodProvider } from "../../contexts/VodContext";

export function Layout() {
    return (
        <VodProvider>
            <div className="app-canvas app-shell flex h-dvh min-h-[100svh] overflow-hidden text-ink font-sans">
                <Sidebar />
                <div className="app-main flex min-h-0 min-w-0 flex-1 flex-col">
                    <Topbar />
                    <main id="main-content" tabIndex={-1} className="relative min-h-0 flex-1 overflow-auto px-3 pb-8 pt-5 sm:px-5 lg:px-7 lg:pt-6">
                        <div className="page-content relative mx-auto max-w-[1680px]">
                            <Outlet />
                        </div>
                    </main>
                </div>
            </div>
        </VodProvider>
    );
}
