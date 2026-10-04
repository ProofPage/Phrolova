import { useCallback, useState } from "react";
import { useToast } from "../components/ui/Toast";
import { getErrorMessage } from "../utils/error";

interface SaveOptions {
    /** 저장 요청 자체. */
    request: () => Promise<unknown>;
    /** 성공했을 때 띄울 문구. */
    success: string;
    /** 실패했을 때 띄울 문구. 서버가 detail을 주면 그쪽이 우선한다. */
    failure: string;
    /** 저장에 성공한 뒤에만 할 일 (입력값 비우기 등). */
    afterSuccess?: () => void;
}

/**
 * 설정 탭의 저장 절차를 한곳에 모은다.
 *
 * 탭마다 "저장 중 표시 → 요청 → 성공 문구 → 상위 갱신 → 실패 문구 → 표시 해제"를
 * 똑같이 반복하고 있었다. 순서를 여기서만 지키게 하고, 탭은 무엇을 저장할지와
 * 어떤 문구를 쓸지만 정한다.
 *
 * 독립적으로 저장되는 영역이 여러 개인 탭은 이 훅을 그만큼 호출하면 된다.
 * 각 호출이 자기 saving 상태를 따로 갖는다.
 */
export function useSettingsSave(onSaved: () => void) {
    const [saving, setSaving] = useState(false);
    const toast = useToast();

    const save = useCallback(
        async ({ request, success, failure, afterSuccess }: SaveOptions) => {
            setSaving(true);
            try {
                await request();
                toast.success(success);
                onSaved();
                afterSuccess?.();
            } catch (error) {
                toast.error(getErrorMessage(error, failure));
            } finally {
                setSaving(false);
            }
        },
        [onSaved, toast],
    );

    return { saving, save };
}
