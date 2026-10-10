import { RecordingChannelCard, type ChannelItemProps } from './RecordingChannelCard';
export function ChannelRow(props: ChannelItemProps) {
    return <RecordingChannelCard {...props} mode="list" />;
}
