import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { build } from 'esbuild';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const result = await build({
    stdin: {
        contents: "export * from './src/utils/error.ts'; export * from './src/i18n/index.ts';",
        resolveDir: root,
        loader: 'ts'
    },
    bundle: true,
    write: false,
    platform: 'node',
    format: 'cjs'
});

const module = { exports: {} };
new Function('module', 'exports', 'require', result.outputFiles[0].text)(module, module.exports, createRequire(import.meta.url));
const {
    getErrorMessage,
    localizedStatus,
    sanitizeSecrets,
    extractDetail,
    isTimeoutError,
    isNetworkError,
    setActiveLocale
} = module.exports;

// ── 1. Structured FastAPI validation error details ──────
setActiveLocale('ko-KR');

// 1a. Array of validation error objects with loc and msg
const fastApiValidation = {
    isAxiosError: true,
    response: {
        status: 422,
        data: {
            detail: [
                { loc: ['body', 'channel_id'], msg: 'Field required', type: 'missing' }
            ]
        }
    }
};
assert.equal(getErrorMessage(fastApiValidation, 'live.couldNotSaveChannelSettings'), 'channel_id: Field required');

// 1b. Multiple validation errors
const multiValidationError = {
    isAxiosError: true,
    response: {
        status: 422,
        data: {
            detail: [
                { loc: ['body', 'channel_id'], msg: 'Field required' },
                { loc: ['body', 'output_format'], msg: "Input should be 'mp4' or 'mkv'" }
            ]
        }
    }
};
assert.equal(
    getErrorMessage(multiValidationError, 'live.couldNotSaveChannelSettings'),
    "channel_id: Field required, output_format: Input should be 'mp4' or 'mkv'"
);

// 1c. Validation error without loc
const noLocValidation = {
    isAxiosError: true,
    response: {
        status: 422,
        data: {
            detail: [{ msg: 'Invalid JSON body' }]
        }
    }
};
assert.equal(getErrorMessage(noLocValidation, 'errors.request'), 'Invalid JSON body');

// 1d. Array of string details
const arrayStringValidation = {
    isAxiosError: true,
    response: {
        status: 422,
        data: {
            detail: ['First error', 'Second error']
        }
    }
};
assert.equal(getErrorMessage(arrayStringValidation, 'errors.request'), 'First error, Second error');

// 1e. Object detail with msg
const objectDetailError = {
    isAxiosError: true,
    response: {
        status: 400,
        data: {
            detail: { msg: '방송 비밀번호는 팝콘티비에서 지원합니다.' }
        }
    }
};
assert.equal(getErrorMessage(objectDetailError, 'errors.request'), '방송 비밀번호는 팝콘티비에서 지원합니다.');

// ── 2. Non-JSON responses (HTML, plain text, gateway errors) ──

// 2a. 502 Bad Gateway with HTML body (must not leak HTML tags or markup)
const html502 = {
    isAxiosError: true,
    response: {
        status: 502,
        data: '<!DOCTYPE html><html><head><title>502 Bad Gateway</title></head><body><h1>502 Bad Gateway</h1><hr><center>nginx</center></body></html>'
    }
};
const res502 = getErrorMessage(html502, 'errors.request');
assert.ok(!res502.includes('<html'), 'HTML tag must not be exposed');
assert.ok(!res502.includes('<!DOCTYPE'), 'Doctype must not be exposed');
assert.ok(!res502.includes('nginx'), 'Internal proxy server banner must not be exposed');
assert.equal(res502, '서버에서 요청을 처리하지 못했습니다. 다시 시도하세요.');

// 2b. 504 Gateway Timeout with HTML body
const html504 = {
    isAxiosError: true,
    response: {
        status: 504,
        data: '<html><body>504 Gateway Time-out</body></html>'
    }
};
assert.equal(getErrorMessage(html504, 'live.couldNotSaveChannelSettings'), '요청 시간이 초과되었습니다. 다시 시도하세요.');

// 2c. 401 Unauthorized with HTML body
const html401 = {
    isAxiosError: true,
    response: {
        status: 401,
        data: '<html><body>401 Unauthorized</body></html>'
    }
};
assert.equal(getErrorMessage(html401, 'errors.request'), '접근 권한이 없습니다. 인증 설정을 확인하세요.');

// 2d. 429 Too Many Requests
const rateLimitError = {
    isAxiosError: true,
    response: {
        status: 429,
        data: 'Too Many Requests'
    }
};
assert.equal(getErrorMessage(rateLimitError, 'errors.request'), '요청이 너무 많습니다. 잠시 후 다시 시도하세요.');

// 2e. Non-JSON plain text error
const plainTextError = {
    isAxiosError: true,
    response: {
        status: 400,
        data: 'Database connection failed'
    }
};
assert.equal(getErrorMessage(plainTextError, 'errors.request'), 'Database connection failed');

// ── 3. Transport failures ───────────────────────────────

// 3a. Axios client timeout without response (ECONNABORTED)
const axiosTimeout = {
    isAxiosError: true,
    code: 'ECONNABORTED',
    message: 'timeout of 10000ms exceeded',
    request: {}
};
assert.equal(isTimeoutError(axiosTimeout), true);
assert.equal(getErrorMessage(axiosTimeout, 'live.couldNotSaveChannelSettings'), '요청 시간이 초과되었습니다. 다시 시도하세요.');

// 3b. Server response with "timeout" in detail must NOT be misclassified as transport timeout
const serverTimeoutDetailError = {
    isAxiosError: true,
    message: 'Request failed with status code 400 timeout',
    response: {
        status: 400,
        data: {
            detail: 'Stream transcode timeout waiting for input frame'
        }
    }
};
assert.equal(isTimeoutError(serverTimeoutDetailError), false);
assert.equal(
    getErrorMessage(serverTimeoutDetailError, 'live.couldNotSaveChannelSettings'),
    'Stream transcode timeout waiting for input frame'
);

// 3c. Axios network error (ERR_NETWORK / connection refused)
const axiosNetwork = {
    isAxiosError: true,
    code: 'ERR_NETWORK',
    message: 'Network Error',
    request: {}
};
assert.equal(isNetworkError(axiosNetwork), true);
assert.equal(getErrorMessage(axiosNetwork, 'live.couldNotSaveChannelSettings'), '서버에 연결하지 못했습니다. 연결 상태를 확인하세요.');

// 3d. Native fetch TypeError: Failed to fetch
const nativeFetchError = new TypeError('Failed to fetch');
assert.equal(isNetworkError(nativeFetchError), true);
assert.equal(getErrorMessage(nativeFetchError, 'live.couldNotSaveChannelSettings'), '서버에 연결하지 못했습니다. 연결 상태를 확인하세요.');

// 3e. Canceled request before timeout/network (must not report as network error or timeout)
const canceledTimeoutError = {
    isAxiosError: true,
    code: 'ERR_CANCELED',
    message: 'timeout of 10000ms exceeded and aborted'
};
assert.equal(isTimeoutError(canceledTimeoutError), false, 'isTimeoutError must return false for canceled error');
assert.equal(isNetworkError(canceledTimeoutError), false, 'isNetworkError must return false for canceled error');
assert.equal(getErrorMessage(canceledTimeoutError, 'live.couldNotSaveChannelSettings'), '채널 설정 저장에 실패했습니다.');

const abortedDomError = new Error('The operation was aborted');
abortedDomError.name = 'AbortError';
assert.equal(isTimeoutError(abortedDomError), false, 'isTimeoutError must return false for AbortError');
assert.equal(isNetworkError(abortedDomError), false, 'isNetworkError must return false for AbortError');

// ── 4. Privacy: Raw secret and credentials sanitization ─

// 4a. Sensitive token / password in URL preserving http / https scheme
const httpUrlMsg = sanitizeSecrets('Connect failed: http://user:secret123@internal.site:8080/stream?token=abc_secret_tok&user=john');
assert.ok(httpUrlMsg.startsWith('Connect failed: http://internal.site:8080/stream'), 'http scheme must be preserved');
assert.ok(!httpUrlMsg.includes('secret123'), 'URL credentials must be stripped');
assert.ok(!httpUrlMsg.includes('abc_secret_tok'), 'Sensitive URL query token must be redacted');
assert.ok(httpUrlMsg.includes('token=[비공개]'));

// 4b. Multi-cookie header masking bound through newline
const cookieHeaderMsg = sanitizeSecrets("Request headers:\nCookie: SID=secret_sid; NID_AUT=secret_nid; session=12345\nContent-Type: application/json");
assert.ok(!cookieHeaderMsg.includes('secret_sid'), 'First cookie must be redacted');
assert.ok(!cookieHeaderMsg.includes('secret_nid'), 'Subsequent cookies in header must be redacted');
assert.ok(!cookieHeaderMsg.includes('12345'), 'Session cookie must be redacted');
assert.ok(cookieHeaderMsg.includes('Cookie: [비공개]'));
assert.ok(cookieHeaderMsg.includes('Content-Type: application/json'), 'Subsequent headers after newline preserved');

// 4c. Authorization Basic & Bearer header masking
const basicAuthMsg = sanitizeSecrets("Authorization: Basic dXNlcjpwYXNz\nNext: line");
assert.ok(!basicAuthMsg.includes('dXNlcjpwYXNz'), 'Basic auth token must be redacted');
assert.ok(basicAuthMsg.includes('Authorization: [비공개]'));

// 4d. Plain token / access_token / refresh_token assignments
const plainTokensMsg = sanitizeSecrets("Failed: token=tok_123, access_token=acc_456, refresh_token=ref_789, password=pw_abc");
assert.ok(!plainTokensMsg.includes('tok_123'));
assert.ok(!plainTokensMsg.includes('acc_456'));
assert.ok(!plainTokensMsg.includes('ref_789'));
assert.ok(!plainTokensMsg.includes('pw_abc'));
assert.ok(plainTokensMsg.includes('token=[비공개]'));
assert.ok(plainTokensMsg.includes('access_token=[비공개]'));
assert.ok(plainTokensMsg.includes('refresh_token=[비공개]'));
assert.ok(plainTokensMsg.includes('password=[비공개]'));

// 4e. JSON-quoted keys (Authorization, Cookie, access_token, password with escaped quotes, preserving unrelated keys)
const jsonPayload = '{"Authorization": "Basic abc", "access_token": "secret_tok", "password": "pass\\"word", "Cookie": "SID=val", "user": "alice", "count": 42}';
const maskedJson = sanitizeSecrets(jsonPayload);
assert.ok(!maskedJson.includes('Basic abc'), 'JSON Authorization value must be masked');
assert.ok(!maskedJson.includes('secret_tok'), 'JSON access_token value must be masked');
assert.ok(!maskedJson.includes('pass\\"word'), 'JSON escaped password value must be masked');
assert.ok(!maskedJson.includes('SID=val'), 'JSON Cookie value must be masked');
assert.ok(maskedJson.includes('"user": "alice"'), 'Unrelated JSON key must not be overconsumed');
assert.ok(maskedJson.includes('"count": 42'), 'Unrelated JSON number key must not be overconsumed');
assert.ok(maskedJson.includes('"Authorization": "[비공개]"'));
assert.ok(maskedJson.includes('"access_token": "[비공개]"'));

// ── 5. Localization preservation ────────────────────────

// 5a. English locale: English error detail is preserved and displayed
setActiveLocale('en-US');
const enError = {
    isAxiosError: true,
    response: {
        status: 400,
        data: {
            detail: 'Invalid channel ID format'
        }
    }
};
assert.equal(getErrorMessage(enError, 'live.couldNotSaveChannelSettings'), 'Invalid channel ID format');

// 5b. English locale: Untranslated Korean detail falls back to localized fallback
const unmappedKoreanError = {
    isAxiosError: true,
    response: {
        status: 400,
        data: {
            detail: '알 수 없는 서버 내부 예외가 발생했습니다.'
        }
    }
};
assert.equal(getErrorMessage(unmappedKoreanError, 'live.couldNotSaveChannelSettings'), 'Could not save channel settings.');

// 5c. English locale: Known alias translated to English
const mappedKoreanError = {
    isAxiosError: true,
    response: {
        status: 400,
        data: {
            detail: '화질 목록을 가져오지 못했습니다. 최고 화질로 녹화하거나 다시 조회하세요.'
        }
    }
};
assert.equal(
    getErrorMessage(mappedKoreanError, 'errors.request'),
    'Could not fetch quality options. Use the highest quality or try again.'
);

// 5d. English locale: 502 HTML error localized in English
assert.equal(getErrorMessage(html502, 'errors.request'), 'The server could not process the request. Try again.');

// 5e. English locale: Timeout localized in English
assert.equal(getErrorMessage(axiosTimeout, 'errors.request'), 'The request timed out. Try again.');

// ── 6. Verification of standard error i18n keys ─────────
for (const locale of ['ko-KR', 'en-US']) {
    setActiveLocale(locale);
    // Ensure verified keys exist and do not fallback to textUnavailable
    for (const key of ['errors.server', 'errors.authentication', 'errors.invalidInput', 'errors.timeout', 'errors.network', 'errors.rateLimited']) {
        const text = module.exports.translate(key);
        assert.ok(text && text !== key && !text.includes('textUnavailable'), `Key ${key} must exist in ${locale}`);
    }
}

// ── 7. localizedStatus helper ───────────────────────────
setActiveLocale('ko-KR');
assert.equal(localizedStatus('치지직 채널 확인 중', 'errors.recording'), '치지직 채널 확인 중');
assert.equal(localizedStatus(null, 'errors.recording'), '녹화에 실패했습니다. 오류 상세를 확인하세요.');

setActiveLocale('en-US');
assert.equal(localizedStatus('CHZZK channel checking', 'errors.recording'), 'CHZZK channel checking');
// Korean status without translation in English locale falls back to key
assert.equal(localizedStatus('치지직 채널 확인 중', 'errors.recording'), 'Recording failed. Check error details.');

console.log('PASS: FastAPI validation detail, non-JSON HTML/gateway responses, transport timeouts/network errors, secret masking and multi-locale preservation');
