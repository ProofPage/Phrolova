import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { RefreshCw, SlidersHorizontal, X } from "lucide-react";
import { api, PLATFORM_LABELS, type Channel, type ChannelDownloadOptions, type DownloadCondition, type LiveQuality, type Platform } from "../../api/client";
import { getErrorMessage } from "../../utils/error";
import { useToast } from "../ui/Toast";
import { Button, Field, Input, Select, SettingRow, Switch } from "../ui/primitives";
import { DOWNLOAD_CONDITIONS } from "./LiveDownloadCondition";
import { useLanguage } from "../../contexts/LanguageContext";

interface Props {
    platform: Platform;
    name: string;
    channel?: Channel;
    channelId?: string;
    onClose: () => void;
    onSave: (options: ChannelDownloadOptions) => Promise<void>;
}

export function ChannelDownloadModal({ platform, name, channel, channelId, onClose, onSave }: Props) {
    const { t } = useLanguage();
    const dialog = useRef<HTMLDialogElement>(null);
    const editedTags = useRef(false);
    const [autoRecord, setAutoRecord] = useState(channel?.auto_record ?? true);
    const [condition, setCondition] = useState<DownloadCondition | "inherit">(channel?.download_condition ?? "inherit");
    const [tags, setTags] = useState(channel?.watchalong_tags ?? "같이보기");
    const [initialTags, setInitialTags] = useState(channel?.watchalong_tags ?? "같이보기");
    const [defaultLabel, setDefaultLabel] = useState("확인 중...");
    const [saving, setSaving] = useState(false);
    const [outputFormat,setOutputFormat] = useState(channel?.output_format || 'inherit');
    const [saveError, setSaveError] = useState<string | null>(null);
    const dynamicQuality = platform === 'soop' || platform === 'cime';
    const [quality, setQuality] = useState(channel?.recording_quality || 'best');
    const [qualities, setQualities] = useState<LiveQuality[]>([]);
    const [qualityLoading, setQualityLoading] = useState(false);
    const [qualityMessage, setQualityMessage] = useState('');
    const [qualityRefresh, setQualityRefresh] = useState(0);
    const dirty = !channel || autoRecord !== channel.auto_record ||
        condition !== (channel.download_condition ?? "inherit") ||
        (condition === "watchalong" && tags !== initialTags) ||
        (dynamicQuality && quality !== (channel?.recording_quality || 'best')) || outputFormat !== (channel?.output_format || 'inherit');
    const toast = useToast();

    useEffect(() => {
        dialog.current?.showModal();
        let active = true;
        void api.getSettings().then((settings) => {
            if (!active) return;
            const label = DOWNLOAD_CONDITIONS.find((item) => item.value === settings.live_download_condition)?.label;
            setDefaultLabel(label || "모든 방송 녹화");
            if (!channel?.watchalong_tags && !editedTags.current) {
                setTags(settings.watchalong_tags || "같이보기");
                setInitialTags(settings.watchalong_tags || "같이보기");
            }
        }).catch(() => { if (active) setDefaultLabel("확인할 수 없음"); });
        return () => { active = false; };
    }, [channel]);

    useEffect(() => {
        if (platform !== 'soop' && platform !== 'cime') return;
        const controller = new AbortController();
        setQualityLoading(true);
        setQualityMessage('');
        void api.getPlatformQualities(platform, channelId || channel?.channel_id || name, controller.signal).then(data => {
            if (controller.signal.aborted) return;
            setQualities(data.qualities.filter(item => !!item.value && item.value !== 'best'));
            setQualityMessage(data.qualities.length ? '현재 방송에서 제공하는 화질입니다. 변경 사항은 다음 녹화부터 적용됩니다.' : data.message || '방송 중일 때 이용 가능한 화질을 확인할 수 있습니다.');
        }).catch(error => {
            if (!controller.signal.aborted) setQualityMessage(getErrorMessage(error, '화질 목록을 가져오지 못했습니다. 최고 화질로 녹화하거나 다시 조회하세요.'));
        }).finally(() => { if (!controller.signal.aborted) setQualityLoading(false); });
        return () => controller.abort();
    }, [platform, channelId, channel?.channel_id, name, qualityRefresh]);

    const save = async () => {
        if (saving) return;
        setSaving(true);
        setSaveError(null);
        try {
            await onSave({
                auto_record: autoRecord,
                download_condition: platform === "chzzk" && condition !== "inherit" ? condition : null,
                watchalong_tags: platform === "chzzk" && condition === "watchalong" ? tags : null,
                ...(dynamicQuality ? { recording_quality: quality } : {}),
                output_format: outputFormat === 'inherit' ? null : outputFormat as 'mp4'|'mkv',
            });
            onClose();
        } catch (error) {
            const message = getErrorMessage(error, t("채널 설정 저장에 실패했습니다."));
            setSaveError(message);
            toast.error(message);
        } finally {
            setSaving(false);
        }
    };

    return createPortal(
        <dialog ref={dialog} aria-labelledby="channel-download-title" onCancel={(event) => { event.preventDefault(); if (!saving) onClose(); }}
            className="ui-dialog m-auto w-[calc(100%_-_2rem)] max-w-lg max-h-[90dvh] overflow-y-auto rounded-[var(--radius-card)] border border-line bg-surface-2 text-ink p-0 shadow-2xl backdrop:bg-black/70">
            <form onSubmit={(event) => { event.preventDefault(); void save(); }} className="p-5 sm:p-6 space-y-5 max-sm:p-3 max-sm:space-y-3">
                <div className="flex items-start gap-3">
                    <SlidersHorizontal className="w-5 h-5 text-[var(--primary)] shrink-0 mt-1" />
                    <div className="flex-1 min-w-0">
                        <h2 id="channel-download-title" className="font-bold text-lg">{channel ? t("채널 녹화 설정") : t("라이브 채널 추가")}</h2>
                        <p className="text-xs text-ink-muted mt-1 truncate" title={name}>{PLATFORM_LABELS[platform]} · {name}</p>
                    </div>
                    <button type="button" onClick={onClose} disabled={saving} aria-label="설정 닫기" className="channel-settings-close icon-button p-1 text-ink-faint hover:text-ink"><X className="w-5 h-5" /></button>
                </div>
                <SettingRow label={t("자동 녹화")} hint={t("방송이 시작되고 녹화 조건에 맞으면 자동으로 저장합니다.")}
                    control={<Switch checked={autoRecord} disabled={saving} onChange={setAutoRecord} label={`${name} ${t("자동 녹화")}`} />} />
                {dynamicQuality && <Field label={t('녹화 화질')} htmlFor="channel-recording-quality" hint={t(qualityMessage || '방송의 화질 정보를 확인하고 있습니다.')}>
                    <div className="flex items-center gap-2 min-w-0">
                        <Select id="channel-recording-quality" className="flex-1 min-w-0" value={quality} disabled={saving || qualityLoading} onChange={event => setQuality(event.target.value)}
                            options={[{ value: 'best', label: t('최고 화질') }, ...qualities.map(item => ({ value: item.value, label: item.label })),
                                ...(quality !== 'best' && !qualities.some(item => item.value === quality) ? [{ value: quality, label: `${t('현재 설정')} · ${quality} (${t('제공 여부 확인 필요')})` }] : [])]} />
                        <Button type="button" icon={RefreshCw} loading={qualityLoading} disabled={saving} aria-label={t('화질 목록 다시 조회')} title={t('화질 목록 다시 조회')} onClick={() => setQualityRefresh(value => value + 1)}>{t('다시 조회')}</Button>
                    </div>
                </Field>}
                <Field label="녹화 완료 후 저장 형식" htmlFor="channel-output-format" hint="변경 사항은 다음 녹화부터 적용됩니다.">
                    <Select id="channel-output-format" value={outputFormat} disabled={saving} onChange={e=>setOutputFormat(e.target.value)} options={[{value:'inherit',label:'전역 설정 사용'},{value:'mkv',label:'MKV'},{value:'mp4',label:'MP4'}]} />
                </Field>
                {platform === "chzzk" && <>
                    <Field label={t("녹화 조건")} htmlFor="channel-download-condition" hint={condition === "inherit" ? `${t("현재 기본값")}: ${t(defaultLabel)}` : t("이 채널에만 적용합니다.")}>
                        <Select id="channel-download-condition" value={condition} autoFocus disabled={saving} onChange={(event) => setCondition(event.target.value as typeof condition)}
                            options={[{ value: "inherit", label: t("기본 조건 사용") }, ...DOWNLOAD_CONDITIONS.map((item) => ({ ...item, label: t(item.label) }))]} />
                    </Field>
                    {channel && <div className="text-xs text-ink-muted flex flex-wrap gap-x-2 gap-y-1"><span className="font-medium">{t("현재 방송 태그")}</span><span className="text-ink-faint">{channel.broadcast_tags == null ? t("확인 대기") : channel.broadcast_tags.length ? channel.broadcast_tags.join(" · ") : t("없음")}</span></div>}
                    {channel?.is_watchalong === true && <p className="text-xs text-[var(--primary)]">{t("치지직 같이보기 방송")}{channel.watchalong_tag ? ` · ${channel.watchalong_tag}` : ""}</p>}
                    {condition === "watchalong" && <Field label={t("같이보기 태그")} htmlFor="channel-watchalong-tags" hint={t("‘같이보기’는 전체 같이보기를 선택합니다. 특정 콘텐츠 태그는 쉼표로 구분하세요.")}>
                        <Input id="channel-watchalong-tags" value={tags} maxLength={500} disabled={saving} onChange={(event) => { editedTags.current = true; setTags(event.target.value); }} placeholder={t("예: 같이보기")} />
                    </Field>}
                    <p className="text-xs text-ink-faint leading-relaxed">{t("치지직의 같이보기 정보와 방송 태그를 확인합니다. 변경 사항은 다음 자동 녹화부터 적용되며, 진행 중인 녹화와 수동 녹화에는 영향을 주지 않습니다.")}</p>
                </>}
                {saveError && <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">{saveError}</p>}
                <div className="dialog-actions flex flex-wrap justify-end gap-2 border-t border-line pt-4">
                    <Button type="button" disabled={saving} onClick={onClose}>취소</Button>
                    <Button type="submit" variant="primary" loading={saving} disabled={!dirty || (platform === "chzzk" && condition === "watchalong" && !tags.trim())}>{channel ? "설정 저장" : "채널 추가"}</Button>
                </div>
            </form>
        </dialog>, document.body,
    );
}
