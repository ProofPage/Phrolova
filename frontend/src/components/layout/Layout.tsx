import { Outlet } from "react-router-dom";
import { Topbar } from "./Topbar";
import { VodProvider } from "../../contexts/VodContext";

export function Layout() {
    return (
        <VodProvider>
            <div className="app-canvas flex h-screen flex-col text-ink font-sans overflow-hidden">
                <Topbar />
                <main id="main-content" className="relative min-h-0 flex-1 overflow-auto px-3 pb-8 pt-5 sm:px-5 lg:px-7 lg:pt-6">
                    <div className="page-content relative max-w-[1680px] mx-auto">
                        <Outlet />
                    </div>
                </main>
            </div>
        </VodProvider>
    );
}
