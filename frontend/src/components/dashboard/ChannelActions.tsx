import type { ReactNode } from 'react';
import { ArrowDown, ArrowUp, ChevronDown, GripVertical, Trash2 } from 'lucide-react';
import { clsx } from 'clsx';
import { ActionMenu } from '../ui/ActionMenu';
import { useLanguage } from '../../contexts/LanguageContext';
import type { ChannelItemProps } from './RecordingChannelCard';

export function ChannelActions(props: ChannelItemProps & { detailsId: string; tagControl: ReactNode }) {
    const { t } = useLanguage();
    const name = props.channel.channel_name || props.channel.channel_id;
    const label = props.isSelected ? "live.collapseDetails" : "live.details";
    return <div className="recording-channel-actions" role="group" aria-label={`${t("live.manageChannel")}: ${name}`}>
        <button type="button" className="icon-button recording-detail-action" onClick={props.onSelect} aria-expanded={!!props.isSelected} aria-controls={props.detailsId} aria-label={`${t(label)}: ${name}`} title={t(label)}><ChevronDown className={clsx('size-4', props.isSelected && 'rotate-180')} /><span>{t(label)}</span></button>
        {props.tagControl}
        <div className="recording-direct-actions">
            <button type="button" className="channel-drag-handle icon-button cursor-grab touch-none select-none active:cursor-grabbing" onPointerDown={props.onReorderPointerDown} onPointerMove={props.onReorderPointerMove} onPointerUp={props.onReorderPointerUp} onPointerCancel={props.onReorderPointerUp} onLostPointerCapture={props.onReorderPointerUp} onMouseMove={props.onReorderMouseMove} onMouseUp={props.onReorderMouseUp} onKeyDown={props.onReorderKeyDown} title={t("live.dragOrUseTheArrowKeysToReorderChannels")} aria-label={`${t("live.reorder")}: ${name}`} aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown"><GripVertical className="size-4 pointer-events-none" /></button>
            <button type="button" className="channel-move-up icon-button" disabled={!props.canMoveUp} onClick={() => props.onMoveChannel(-1)} title={t("live.moveUp")} aria-label={`${t("live.moveUp")}: ${name}`}><ArrowUp className="size-4" /></button>
            <button type="button" className="channel-move-down icon-button" disabled={!props.canMoveDown} onClick={() => props.onMoveChannel(1)} title={t("live.moveDown")} aria-label={`${t("live.moveDown")}: ${name}`}><ArrowDown className="size-4" /></button>
            <button type="button" className="icon-button hover:text-danger" disabled={props.isActionLoading} onClick={() => props.onRemove(props.channel)} aria-label={`${t("live.removeChannel")}: ${name}`} title={t("live.removeChannel")}><Trash2 className="size-4" /></button>
        </div>
        <ActionMenu className="recording-more channel-card-more" label={`${t("live.manageChannel")}: ${name}`} onKeyDown={props.onReorderKeyDown}>{close => <>
            <button type="button" disabled={!props.canMoveUp} onClick={() => { props.onMoveChannel(-1); close(); }}><ArrowUp className="size-4" />{t("live.moveUp")}</button>
            <button type="button" disabled={!props.canMoveDown} onClick={() => { props.onMoveChannel(1); close(); }}><ArrowDown className="size-4" />{t("live.moveDown")}</button>
            <button type="button" disabled={props.isActionLoading} className="text-danger" onClick={() => { close(); props.onRemove(props.channel); }}><Trash2 className="size-4" />{t("live.removeChannel")}</button>
        </>}</ActionMenu>
    </div>;
}
