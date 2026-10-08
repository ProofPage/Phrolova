import { ArrowDown, ArrowUp, ChevronDown, GripVertical, Tags, Trash2 } from "lucide-react";
import { clsx } from "clsx";
import { ActionMenu } from "../ui/ActionMenu";
import { useLanguage } from "../../contexts/LanguageContext";
import type { ChannelItemProps } from "./ChannelCard";

export function ChannelActions({ showDetails = true, card = false, compactMenu = false, onManageTags, ...props }: ChannelItemProps & { showDetails?: boolean; card?: boolean; compactMenu?: boolean; onManageTags?: () => void }) {
    const { t } = useLanguage();
    const name = props.channel.channel_name || props.channel.channel_id;
    return <div className="channel-header-actions" role="group" aria-label={`${t("채널 관리")}: ${name}`}>
        {(card || compactMenu) && <ActionMenu className="channel-mobile-more channel-card-more" label={`${t("채널 관리")}: ${name}`} onKeyDown={props.onReorderKeyDown}>{close => <>
            <button type="button" disabled={!props.canMoveUp} onClick={() => { props.onMoveChannel(-1); close(); }}><ArrowUp className="size-4" />{t("위로 이동")}</button>
            <button type="button" disabled={!props.canMoveDown} onClick={() => { props.onMoveChannel(1); close(); }}><ArrowDown className="size-4" />{t("아래로 이동")}</button>
            {onManageTags && <button type="button" onClick={() => { close(); onManageTags(); }}><Tags className="size-4" />{t("태그 관리")}{!!props.channel.tags?.length && <span className="ml-auto tabular-nums">{props.channel.tags.length}</span>}</button>}
            <button type="button" className="text-danger" onClick={() => { close(); props.onRemove(props.channel); }}><Trash2 className="size-4" />{t("채널 제거")}</button>
        </>}</ActionMenu>}
        <div className="channel-primary-actions">
            <button type="button" onPointerDown={props.onReorderPointerDown} onPointerMove={props.onReorderPointerMove} onPointerUp={props.onReorderPointerUp} onPointerCancel={props.onReorderPointerUp} onLostPointerCapture={props.onReorderPointerUp} onMouseMove={props.onReorderMouseMove} onMouseUp={props.onReorderMouseUp} onKeyDown={props.onReorderKeyDown} className="channel-drag-handle icon-button cursor-grab touch-none select-none active:cursor-grabbing" title={t("드래그하거나 방향키를 눌러 채널 순서 변경")} aria-label={`${name} ${t("채널 순서 변경")}`} aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown"><GripVertical className="size-4 pointer-events-none" /></button>
            <button type="button" className="channel-delete-action icon-button hover:text-danger" onClick={() => props.onRemove(props.channel)} aria-label={`${t("채널 제거")}: ${name}`} title={t("채널 제거")}><Trash2 className="size-4" /></button>
        </div>
        <div className="channel-secondary-actions channel-reorder-actions">
            <button type="button" className="channel-move-up icon-button" disabled={!props.canMoveUp} onClick={() => props.onMoveChannel(-1)} aria-label={`${t("위로 이동")}: ${name}`}><ArrowUp className="size-4" /></button>
            <button type="button" className="channel-move-down icon-button" disabled={!props.canMoveDown} onClick={() => props.onMoveChannel(1)} aria-label={`${t("아래로 이동")}: ${name}`}><ArrowDown className="size-4" /></button>
            {showDetails && <button type="button" className={clsx("channel-detail-action icon-button", card && "channel-card-detail")} onClick={props.onSelect} aria-expanded={!!props.isSelected} aria-label={`${t(props.isSelected ? "상세 접기" : "채널 상세 보기")}: ${name}`} title={t(props.isSelected ? "상세 접기" : "채널 상세 보기")}><ChevronDown className={clsx("size-4", props.isSelected && "rotate-180")} />{card && <span>{t(props.isSelected ? "상세 접기" : "상세 보기")}</span>}</button>}
        </div>
    </div>;
}
