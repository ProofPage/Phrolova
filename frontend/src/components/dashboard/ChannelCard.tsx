import { RecordingChannelCard, type ChannelItemProps } from './RecordingChannelCard';
export type { ChannelItemProps } from './RecordingChannelCard';
export function ChannelCard(props: ChannelItemProps & { isFullWidth?: boolean }) {
    return <RecordingChannelCard {...props} mode="grid" />;
}
