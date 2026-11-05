// Carrega src/index.js para os testes em Node expondo as funções internas. O Worker publicado só exporta o handler
// padrão, porque o runtime do Cloudflare recusa exports nomeados que não sejam handlers.
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const src = readFileSync(new URL('../src/index.js', import.meta.url), 'utf8');
const names = ['VERSION', 'ENDPOINT_DEFAULT', 'sanitize', 'challengeResponse', 'parseSignatureHeader', 'derToP1363', 'verifyEcdsaSha1',
  'getPublicKey', 'validateMessage', 'syncSignature', 'selftest', 'handle'];
const dir = mkdtempSync(join(tmpdir(), 'gpi-worker-'));
const f = join(dir, 'index.mjs');
writeFileSync(f, src + `\nexport { ${names.join(', ')} };\nexport const scheduled = runScheduled;\n`);
export const W = await import(pathToFileURL(f).href);
