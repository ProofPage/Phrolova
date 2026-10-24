import { useLanguage } from "../../contexts/LanguageContext";
import { RecordingChannelCard, type ChannelItemProps } from './RecordingChannelCard';
export type { ChannelItemProps } from './RecordingChannelCard';
export function ChannelCard(props: ChannelItemProps & { isFullWidth?: boolean }) {
    useLanguage();
    return <RecordingChannelCard {...props} mode="grid" />;
}
