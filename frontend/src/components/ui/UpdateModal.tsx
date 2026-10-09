import { useDialogKeyboard } from "../../hooks/useDialogKeyboard";
import { useRef, useState } from "react";
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
 * `rookery` 명령을 못 찾는 사람에게는 이게 유일한 탈출구인데, 예전에는 본문에서
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

    const handleCopy = () => {
        navigator.clipboard.writeText(command);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
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
                aria-label={t("명령 복사")}
                className="icon-button absolute top-2 right-2 bg-surface-3 hover:bg-surface-4 text-ink-faint hover:text-ink rounded-md transition-colors"
            >
                {copied ? <CheckCircle2 className="w-4 h-4 text-ok" /> : <Copy className="w-4 h-4" />}
            </button>
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
                            Windows 데스크톱 환경에서는 브라우저에서 최신 버전을 직접 다운로드하여 설치해야 합니다.
                        </p>
                        <div className="bg-surface-1 p-4 rounded-[var(--radius-control)] border border-line">
                            <ol className="list-decimal list-inside space-y-2 text-sm text-ink-muted">
                                <li>아래 버튼을 눌러 GitHub 릴리즈 페이지로 이동합니다.</li>
                                <li><span className="text-[var(--primary)] font-mono break-all">{assetName}</span> 파일을 다운로드합니다.</li>
                                <li>현재 실행 중인 프로그램을 종료합니다.</li>
                                <li>
                                    받은 파일을 <b className="text-ink-muted">기존 실행 파일과 같은 폴더</b>로 옮긴 뒤 실행합니다.
                                </li>
                                <li>정상 동작을 확인했으면 이전 버전 파일은 삭제해도 됩니다.</li>
                            </ol>
                        </div>
                        <p className="text-xs text-ink-faint flex items-start gap-1.5">
                            <span className="text-warn">⚠️</span>
                            <span>
                                설정(<span className="font-mono">.env</span>)과 데이터(<span className="font-mono">data/</span>)는
                                실행 파일 옆에 저장됩니다. 다른 폴더에서 실행하면 채널 목록이 비어 보이고 초기 설정 마법사가 다시 표시됩니다.
                            </span>
                        </p>
                        <a
                            href={info.download_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="ui-button w-full btn-primary py-2.5 rounded-[var(--radius-control)] font-bold transition-colors flex items-center justify-center gap-2"
                        >
                            <ExternalLink className="w-4 h-4" />
                            GitHub 릴리즈에서 다운로드
                        </a>
                    </div>
                );
            }
            case "termux-native":
            case "termux-proot":
            case "windows-native":
            case "macos-native":
                return (
                    <div className="space-y-3">
                        <p className="text-sm text-ink-muted">서버를 중지하고 저장소를 갱신한 뒤 환경별 설치 가이드에 따라 의존성과 웹 UI를 다시 준비하세요.</p>
                        <CommandBlock command="git pull --ff-only" />
                        <p className="text-xs text-ink-faint">docs/linux-guide.md 및 docs/termux-guide.md를 확인하세요. 기존 설정과 데이터는 유지하세요.</p>
                    </div>
                );
            case "linux-native":
            default:
                // 네이티브는 manage.sh가 등록한 rookery 명령으로 끝난다.
                return (
                    <div className="space-y-4">
                        <p className="text-sm text-ink-muted">
                            터미널에서 아래 명령을 실행하면 최신 버전으로 갱신한 뒤 자동으로 재시작됩니다.
                        </p>
                        <CommandBlock command="rookery update" />

                        {/*
                          코드를 git pull로만 갱신해 온 사용자는 link_self()가 한 번도 돌지 않아
                          rookery 명령 자체가 없다. 여기서 빠져나갈 길을 주지 않으면 막힌다.
                        */}
                        <div className="border-t border-line pt-4 space-y-2.5">
                            <p className="text-sm text-ink-muted">
                                <span className="font-mono text-warn">command not found</span> 가 나오나요?
                            </p>
                            <p className="text-xs text-ink-faint leading-relaxed">
                                코드를 <span className="font-mono">git pull</span> 로만 갱신해 왔다면 명령이 등록되지 않았을 수 있습니다.
                                아래 설치 원라이너가 업데이트를 겸하며, <span className="font-mono">rookery</span> 명령도 함께 등록합니다.
                            </p>
                            <CommandBlock command={INSTALL_ONE_LINER} />
                        </div>

                        <p className="text-xs text-ink-faint">
                            시스템 패키지를 다룰 때 sudo 비밀번호를 물을 수 있습니다.
                        </p>
                    </div>
                );
        }
    };

    return (
        <div className="ui-overlay fixed inset-0 z-[9998] flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/60 " onClick={onClose} />
            <div ref={dialogRootRef} role="dialog" aria-modal="true" aria-label={t("업데이트 안내")} tabIndex={-1} className="relative bg-surface-2 border border-line-strong rounded-[var(--radius-card)] ui-dialog w-full min-w-0 max-w-lg flex flex-col overflow-hidden shadow-2xl surface-raise animate-modal-in">
                <div className="flex items-center justify-between gap-2 p-4 shrink-0 border-b border-line">
                    <h3 className="text-lg font-bold text-ink flex items-center gap-2">
                        <Terminal className="w-5 h-5 text-[var(--primary)]" />
                        업데이트 안내
                    </h3>
                    <button
                        onClick={onClose}
                        aria-label={t("닫기")} className="icon-button"
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
