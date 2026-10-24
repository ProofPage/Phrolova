import { Plus, Trash2 } from "lucide-react";
import type { ChannelMonitorSchedule, ScheduleWindow } from "../../api/client";
import { Button, Field, Input, Select } from "../ui/primitives";
import { useLanguage } from "../../contexts/LanguageContext";
import "./channel-schedule.css";

/** 요일은 JS Date.getDay()와 맞춘 일요일=0 순서. 서버에는 월요일=0으로 보낸다. */
const DAYS = [
    { label: "live.scheduleDaySun", server: 6 },
    { label: "live.scheduleDayMon", server: 0 },
    { label: "live.scheduleDayTue", server: 1 },
    { label: "live.scheduleDayWed", server: 2 },
    { label: "live.scheduleDayThu", server: 3 },
    { label: "live.scheduleDayFri", server: 4 },
    { label: "live.scheduleDaySat", server: 5 },
];

export const DEFAULT_SCHEDULE: ChannelMonitorSchedule = { mode: "always", windows: [], lead_minutes: 10, delay_minutes: 30 };

/** 저장된 JSON을 편집 가능한 상태로 읽는다. 깨졌으면 기본값. */
export function readSchedule(raw?: string | null): ChannelMonitorSchedule {
    if (!raw) return DEFAULT_SCHEDULE;
    try {
        const data = JSON.parse(raw);
        if (!data || (data.mode !== 'always' && data.mode !== 'scheduled')) return DEFAULT_SCHEDULE;
        return {
            mode: data.mode,
            windows: Array.isArray(data.windows) ? data.windows.map((window: ScheduleWindow) => ({ days: window.days ?? [], start: window.start, end: window.end })) : [],
            lead_minutes: Number(data.lead_minutes ?? 10),
            delay_minutes: Number(data.delay_minutes ?? 30),
        };
    } catch {
        return DEFAULT_SCHEDULE;
    }
}

/** 예약 감시 여부와 요일·시간대를 편집한다. */
export function ChannelScheduleFields({ value, disabled, onChange }: {
    value: ChannelMonitorSchedule;
    disabled: boolean;
    onChange: (value: ChannelMonitorSchedule) => void;
}) {
    const { t } = useLanguage();
    const scheduled = value.mode === 'scheduled';
    const update = (patch: Partial<ChannelMonitorSchedule>) => onChange({ ...value, ...patch });
    const updateWindow = (index: number, patch: Partial<ScheduleWindow>) =>
        update({ windows: value.windows.map((window, position) => position === index ? { ...window, ...patch } : window) });
    const toggleDay = (index: number, server: number) => {
        const days = value.windows[index].days;
        updateWindow(index, { days: days.includes(server) ? days.filter(day => day !== server) : [...days, server].sort((a, b) => a - b) });
    };
    return <div className="channel-schedule">
        <Field label={t("live.monitorSchedule")} htmlFor="channel-monitor-mode"
            hint={scheduled ? t("live.monitorScheduleHint") : t("live.monitorAlwaysHint")}>
            <Select id="channel-monitor-mode" value={value.mode} disabled={disabled}
                onChange={event => {
                    const mode = event.target.value as ChannelMonitorSchedule['mode'];
                    update(mode === 'scheduled' && value.windows.length === 0
                        ? { mode, windows: [{ days: [0, 1, 2, 3, 4, 5, 6], start: '20:00', end: '23:00' }] }
                        : { mode });
                }}
                options={[{ value: 'always', label: t("live.monitorAlways") }, { value: 'scheduled', label: t("live.monitorScheduled") }]} />
        </Field>
        {scheduled && <>
            {value.windows.map((window, index) => <div key={index} className="channel-schedule-window" role="group" aria-label={`${t("live.scheduleWindow")} ${index + 1}`}>
                <div className="channel-schedule-window-heading">
                    <span className="ui-field-label">{t("live.scheduleWindow")} {index + 1}</span>
                    <Button type="button" icon={Trash2} disabled={disabled || value.windows.length === 1}
                        aria-label={t("live.scheduleRemoveWindow")} title={t("live.scheduleRemoveWindow")}
                        onClick={() => update({ windows: value.windows.filter((_, position) => position !== index) })}>
                        {t("live.scheduleRemoveWindow")}
                    </Button>
                </div>
                <div className="channel-schedule-pair">
                    <Field label={t("live.scheduleStart")} htmlFor={`schedule-start-${index}`}>
                        <Input id={`schedule-start-${index}`} type="time" value={window.start} disabled={disabled}
                            onChange={event => updateWindow(index, { start: event.target.value })} />
                    </Field>
                    <Field label={t("live.scheduleEnd")} htmlFor={`schedule-end-${index}`}>
                        <Input id={`schedule-end-${index}`} type="time" value={window.end} disabled={disabled}
                            onChange={event => updateWindow(index, { end: event.target.value })} />
                    </Field>
                </div>
                <fieldset className="min-w-0">
                    <legend className="ui-field-label">{t("live.scheduleDays")}</legend>
                    <div className="channel-schedule-days">
                        {DAYS.map(day => {
                            const active = window.days.includes(day.server);
                            return <button key={day.server} type="button" disabled={disabled} aria-pressed={active}
                                onClick={() => toggleDay(index, day.server)}
                                className={`ui-button ${active ? 'btn-primary' : ''}`}>{t(day.label)}</button>;
                        })}
                    </div>
                </fieldset>
            </div>)}
            <Button className="channel-schedule-add" type="button" icon={Plus} disabled={disabled} onClick={() => update({ windows: [...value.windows, { days: [0, 1, 2, 3, 4, 5, 6], start: '20:00', end: '23:00' }] })}>
                {t("live.scheduleAddWindow")}
            </Button>
            <div className="channel-schedule-pair channel-schedule-offsets">
                <Field label={`${t("live.scheduleLead")} (${t("live.scheduleMinutes")})`} htmlFor="schedule-lead"
                    hint={t("live.scheduleLeadHint")}>
                    <Input id="schedule-lead" type="number" min={0} max={180} value={value.lead_minutes} disabled={disabled}
                        onChange={event => update({ lead_minutes: Number(event.target.value) })} />
                </Field>
                <Field label={`${t("live.scheduleDelay")} (${t("live.scheduleMinutes")})`} htmlFor="schedule-delay"
                    hint={t("live.scheduleDelayHint")}>
                    <Input id="schedule-delay" type="number" min={0} max={360} value={value.delay_minutes} disabled={disabled}
                        onChange={event => update({ delay_minutes: Number(event.target.value) })} />
                </Field>
            </div>
        </>}
    </div>;
}
