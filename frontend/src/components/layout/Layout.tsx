import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { VodProvider } from "../../contexts/VodContext";

export function Layout() {
    return (
        <VodProvider>
            <div className="app-canvas flex h-screen text-ink font-sans overflow-hidden">
                <Sidebar />
                <main className="relative flex-1 overflow-auto px-4 pb-8 pt-16 sm:px-6 lg:px-8 lg:py-8">
                    <div className="page-content relative max-w-[1480px] mx-auto">
                        <Outlet />
                    </div>
                </main>
            </div>
        </VodProvider>
    );
}
