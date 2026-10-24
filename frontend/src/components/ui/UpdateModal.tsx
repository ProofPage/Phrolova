import { translate } from "../../i18n";
import { useDialogKeyboard } from "../../hooks/useDialogKeyboard";
import { useEffect, useRef, useState } from "react";
import { X, ExternalLink, Copy, CheckCircle2, Terminal } from "lucide-react";
import { useLanguage } from "../../contexts/LanguageContext";
import { UpdateInfo } from "../../api/client";

interface UpdateModalProps {
    info: UpdateInfo;
    onClose: () => void;
}

/**
 * 설치와 업데이트를 겸하는 원라이너. scripts/manage.sh 상단의 RAW_URL과 같은 주소다.
 *
 * `phrolova` 명령을 못 찾는 사람에게는 이게 유일한 탈출구인데, 예전에는 본문에서
 * "원라이너를 실행하라"고 말만 하고 정작 그 명령을 보여주지 않아 README를 뒤져야 했다.
 */
const INSTALL_ONE_LINER =
    "curl -fsSL https://raw.githubusercontent.com/ProofPage/Phrolova/main/scripts/manage.sh | bash";

/**
 * 복사 버튼이 달린 명령 블록.
 *
 * 복사 상태를 블록마다 따로 갖는다. 상위에서 하나로 공유하면 어느 것을 눌러도
 * 모든 블록에 체크 표시가 떠서 무엇을 복사했는지 알 수 없다.
 */
function CommandBlock({ command }: { command: string }) {
    const { t } = useLanguage();
    const [copied, setCopied] = useState(false);
    const [copyError, setCopyError] = useState(false);
    const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
    const mounted = useRef(true);
    useEffect(() => { mounted.current = true; return () => { mounted.current = false; clearTimeout(timer.current); }; }, []);

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(command);
            if (!mounted.current) return;
            setCopyError(false); setCopied(true);
            clearTimeout(timer.current);
            timer.current = setTimeout(() => setCopied(false), 2000);
        } catch {
            if (mounted.current) setCopyError(true);
        }
    };

    return (
        <div className="relative group">
            <div className="bg-surface-1 border border-line rounded-[var(--radius-control)] command-code p-3 pr-16 overflow-x-auto">
                <code className="text-xs text-[var(--primary)] font-mono whitespace-nowrap">
                    {command}
                </code>
            </div>
            <button
                onClick={handleCopy}
                aria-label={t("common.copyCommand")}
                className="icon-button absolute top-2 right-2 bg-surface-3 hover:bg-surface-4 text-ink-faint hover:text-ink rounded-md transition-colors"
            >
                {copied ? <CheckCircle2 className="w-4 h-4 text-ok" /> : <Copy className="w-4 h-4" />}
            </button>
            {copyError && <p role="status" className="mt-1 text-xs text-warn">{translate("common.couldNotCopyToClipboardSelectTheCommandAndCopyItManually")}</p>}
        </div>
    );
}

export function UpdateModal({ info, onClose }: UpdateModalProps) {
    const { t } = useLanguage();
    const dialogRootRef = useRef<HTMLDivElement>(null);
    useDialogKeyboard(dialogRootRef, onClose);
    const renderContent = () => {
        switch (info.environment) {
            case "windows-exe": {
                // 릴리즈 asset 이름에 버전이 들어간다: Phrolova-v2.0.0-windows-x64.exe
                const assetName = `Phrolova-v${info.latest_version}-windows-x64.exe`;
                return (
                    <div className="space-y-4">
                        <p className="text-sm text-ink-muted">
                            {translate("common.onWindowsDesktopDownloadAndInstallTheLatestVersionUsingYourBrowser")}</p>
                        <div className="bg-surface-1 p-4 rounded-[var(--radius-control)] border border-line">
                            <ol className="list-decimal list-inside space-y-2 text-sm text-ink-muted">
                                <li>{translate("common.useTheButtonBelowToOpenTheGitHubReleasePage")}</li>
                                <li className="break-words">{translate("common.downloadInstallerFile", {filename: assetName})}</li>
                                <li>{translate("common.exitTheRunningApp")}</li>
                                <li>
                                    {translate("common.moveInstallerAndRun")}</li>
                                <li>{translate("common.afterConfirmingItWorksYouCanDeleteThePreviousVersion")}</li>
                            </ol>
                        </div>
                        <p className="text-xs text-ink-faint flex items-start gap-1.5">
                            <span className="text-warn">⚠️</span>
                            <span>
                                {translate("common.settingsAndDataLocation", {settings: ".env", data: "data/"})}</span>
                        </p>
                        <a
                            href={info.download_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="ui-button w-full btn-primary py-2.5 rounded-[var(--radius-control)] font-bold transition-colors flex items-center justify-center gap-2"
                        >
                            <ExternalLink className="w-4 h-4" />
                            {translate("common.downloadFromGitHubReleases")}</a>
                    </div>
                );
            }
            case "termux-native":
            case "termux-proot":
            case "windows-native":
            case "macos-native":
                return (
                    <div className="space-y-3">
                        <p className="text-sm text-ink-muted">{translate("common.stopTheServerUpdateTheRepositoryThenFollowTheInstallationGuideForYourEnvironmentToPrepareDependenciesAndTheWebUIAgain")}</p>
                        <CommandBlock command="git pull --ff-only" />
                        <p className="text-xs text-ink-faint">{translate("common.seeDocsLinuxGuideMdAndDocsTermuxGuideMdKeepYourExistingSettingsAndData")}</p>
                    </div>
                );
            case "linux-native":
            default:
                // 네이티브는 manage.sh가 등록한 phrolova 명령으로 끝난다.
                return (
                    <div className="space-y-4">
                        <p className="text-sm text-ink-muted">
                            {translate("common.runTheCommandBelowInYourTerminalToUpdateToTheLatestVersionAndRestartAutomatically")}</p>
                        <CommandBlock command="phrolova update" />

                        {/*
                          코드를 git pull로만 갱신해 온 사용자는 link_self()가 한 번도 돌지 않아
                          phrolova 명령 자체가 없다. 여기서 빠져나갈 길을 주지 않으면 막힌다.
                        */}
                        <div className="border-t border-line pt-4 space-y-2.5">
                            <p className="text-sm text-ink-muted">
                                {translate("common.commandNotFoundHelp", {command: "command not found"})}</p>
                            <p className="text-xs text-ink-faint leading-relaxed">
                                {translate("common.registerUpdateCommand", {git: "git pull", command: "phrolova"})}</p>
                            <CommandBlock command={INSTALL_ONE_LINER} />
                        </div>

                        <p className="text-xs text-ink-faint">
                            {translate("common.youMayBeAskedForYourSudoPasswordWhenManagingSystemPackages")}</p>
                    </div>
                );
        }
    };

    return (
        <div className="ui-overlay fixed inset-0 z-[9998] flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/60 " onClick={onClose} />
            <div ref={dialogRootRef} role="dialog" aria-modal="true" aria-label={t("common.updateInstructions")} tabIndex={-1} className="relative bg-surface-2 border border-line-strong rounded-[var(--radius-card)] ui-dialog w-full min-w-0 max-w-lg flex flex-col overflow-hidden shadow-2xl surface-raise animate-modal-in">
                <div className="flex items-center justify-between gap-2 p-4 shrink-0 border-b border-line">
                    <h3 className="text-lg font-bold text-ink flex items-center gap-2">
                        <Terminal className="w-5 h-5 text-[var(--primary)]" />
                        {translate("common.updateInstructions")}</h3>
                    <button
                        onClick={onClose}
                        aria-label={t("common.close")} className="icon-button"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <div className="min-h-0 overflow-y-auto overscroll-contain p-4 sm:p-6 [overflow-wrap:anywhere]">
                    {renderContent()}
                </div>
            </div>
        </div>
    );
}
