'use strict';
// Trusted local ABI bridge, not the site's JavaScript. WASM has no WASI,
// filesystem, network or process imports. The only callback materializes text.
const fs = require('node:fs');
const crypto = require('node:crypto');
try {
  const buffer = Buffer.alloc(800001);
  let length = 0;
  while (length < buffer.length) {
    const count = fs.readSync(0, buffer, length, buffer.length - length, null);
    if (!count) break;
    length += count;
  }
  if (length > 800000) throw Error();
  const input = buffer.subarray(0, length);
  const data = JSON.parse(input);
  if (typeof data.session !== 'string' || Buffer.byteLength(data.session) > 65536) throw Error();
  const session = JSON.parse(data.session);
  if (!session || session.key_length !== 16) throw Error();
  if (session.version === 10) {
    if (session.total_layers !== 10 || !Array.isArray(session.layers) || session.layers.length !== 10) throw Error();
  } else if (session.version === 11) {
    const fields = {encrypted_key: 1024, bytecode_cipher: 32768, bytecode_nonce: 256, session_seed: 256};
    if (Object.keys(session).length !== 6 || Object.entries(fields).some(([name, cap]) =>
        typeof session[name] !== 'string' || session[name].length < 1 || session[name].length > cap)) throw Error();
  } else throw Error();
  const bytes = Buffer.from(data.module, 'base64');
  if (bytes.length > 524288 || crypto.createHash('sha384').update(bytes).digest('hex') !==
      '11ba14e9a68f13eaac9a5664056209bfd11302382e4c18bfe8f629af4ed0d7e80a69cc9b72fd339a0b8ee8d5461e0a72') throw Error();
  const mod = new WebAssembly.Module(bytes);
  const imports = WebAssembly.Module.imports(mod);
  if (imports.length !== 1 || imports[0].module !== './level5_decryptor_bg.js' ||
      imports[0].name !== '__wbindgen_cast_0000000000000001' || imports[0].kind !== 'function') throw Error();
  let wasm;
  let errorCount = 0;
  const instance = new WebAssembly.Instance(mod, {
    './level5_decryptor_bg.js': {
      __wbindgen_cast_0000000000000001: (ptr, len) => {
        if (len > 4096 || ++errorCount > 32) throw Error();
        // Only errors use this callback; no remote text is emitted.
        new TextDecoder('utf-8', {fatal: true}).decode(new Uint8Array(wasm.memory.buffer, ptr, len));
        return 1028;
      },
    },
  });
  wasm = instance.exports;
  const text = new TextEncoder().encode(data.session);
  const ptr = wasm.__wbindgen_export(text.length, 1);
  new Uint8Array(wasm.memory.buffer, ptr, text.length).set(text);
  const stack = wasm.__wbindgen_add_to_stack_pointer(-16);
  wasm.decode_session(stack, ptr, text.length);
  const view = new DataView(wasm.memory.buffer);
  const out = view.getUint32(stack, true);
  const size = view.getUint32(stack + 4, true);
  if (view.getInt32(stack + 12, true) || errorCount || size !== 16) throw Error();
  process.stdout.write(Buffer.from(new Uint8Array(wasm.memory.buffer, out, size)));
} catch (_) {
  process.exitCode = 1;
}
