import { useEffect, useState } from 'react';
import { Radio } from 'lucide-react';
import type { Platform, StreamlinkOptionsByPlatform } from '../../api/client';
import { useLanguage } from '../../contexts/LanguageContext';
import { Card, CardHeader, Field, Input, Select } from '../ui/primitives';

const platforms: Platform[] = ['chzzk', 'youtube', 'cime', 'kick', 'twitch', 'tiktok', 'bilibili', 'pandalive', 'popkontv', 'rplay', 'twitcasting', 'spoon'];

export function streamlinkOptionsKey(value: StreamlinkOptionsByPlatform): string {
    return JSON.stringify(platforms.flatMap(platform => {
        const options = value[platform];
        const parameters = options?.query_parameters ?? {};
        if (!options?.playlist_reload_seconds && !Object.keys(parameters).length) return [];
        return [[platform, options?.playlist_reload_seconds ?? 0,
            Object.keys(parameters).sort().map(key => [key, parameters[key]])]];
    }));
}

function parseParameters(text: string): Record<string, string> | null {
    try {
        const value: unknown = JSON.parse(text);
        if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
        const entries = Object.entries(value);
        if (entries.length > 32 || entries.some(([key, item]) =>
            !key.trim() || key.length > 128 || typeof item !== 'string' || item.length > 4096 || /[\x00-\x1f\x7f]/.test(key + item))) return null;
        return Object.fromEntries(entries);
    } catch {
        return null;
    }
}

export function StreamlinkSettingsCard({ value, onChange, onValidityChange }: {
    value: StreamlinkOptionsByPlatform;
    onChange: (value: StreamlinkOptionsByPlatform) => void;
    onValidityChange: (valid: boolean) => void;
}) {
    const { t } = useLanguage();
    const [platform, setPlatform] = useState<Platform>('chzzk');
    const [drafts, setDrafts] = useState<Partial<Record<Platform, string>>>({});
    const options = value[platform] ?? { playlist_reload_seconds: 0, query_parameters: {} };
    const draft = drafts[platform] ?? JSON.stringify(options.query_parameters, null, 2);
    const validQueries = Object.values(drafts).every(text => parseParameters(text) !== null);
    const validDelays = Object.values(value).every(option => option && Number.isFinite(option.playlist_reload_seconds) &&
        (option.playlist_reload_seconds === 0 || option.playlist_reload_seconds >= 2) && option.playlist_reload_seconds <= 60);
    useEffect(() => onValidityChange(validQueries && validDelays), [validQueries, validDelays, onValidityChange]);

    return <Card className="settings-section space-y-3" data-settings-section="transport">
        <CardHeader icon={Radio} title={t('settings.streamlinkSettings')} />
        <Field label={t('settings.streamlinkPlatform')}>
            <Select value={platform} onChange={event => setPlatform(event.target.value as Platform)}
                options={platforms.map(item => ({ value: item, label: t(`platform.${item}`) }))} />
        </Field>
        <Field label={t('settings.playlistReloadSeconds')} hint={t('settings.playlistReloadHint')}>
            <Input type="number" min={0} max={60} step={1} value={options.playlist_reload_seconds}
                onChange={event => onChange({ ...value, [platform]: { ...options, playlist_reload_seconds: Number(event.target.value) } })} />
        </Field>
        <Field label={t('settings.streamQueryParameters')} hint={t('settings.streamQueryHint')}>
            <textarea className="ui-input min-h-28 font-mono text-xs" value={draft} rows={4}
                aria-label={t('settings.streamQueryParameters')} aria-invalid={parseParameters(draft) === null}
                onChange={event => {
                    const text = event.target.value;
                    setDrafts(previous => ({ ...previous, [platform]: text }));
                    const parsed = parseParameters(text);
                    if (parsed !== null) onChange({ ...value, [platform]: { ...options, query_parameters: parsed } });
                }} />
            {parseParameters(draft) === null && <p role="alert" className="text-xs text-danger">{t('settings.invalidStreamQuery')}</p>}
        </Field>
    </Card>;
}
