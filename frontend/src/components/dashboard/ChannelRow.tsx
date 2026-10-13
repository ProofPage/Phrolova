import { useLanguage } from "../../contexts/LanguageContext";
import { RecordingChannelCard, type ChannelItemProps } from './RecordingChannelCard';
export function ChannelRow(props: ChannelItemProps) {
    useLanguage();
    return <RecordingChannelCard {...props} mode="list" />;
}
