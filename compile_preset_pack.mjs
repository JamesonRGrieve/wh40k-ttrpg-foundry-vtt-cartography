#!/usr/bin/env node
/**
 * Compile the JSON document tree at `dh-cartography/packs-src/dh-presets-journals/`
 * into a Foundry V14 LevelDB compendium pack at `dh-cartography/packs/dh-presets-journals/`.
 *
 * Schema mirrors the wh40k-rpg system's gulpfile compiler: each document is
 * stored under the key `!journal!<_id>`. Mass Edit's Preset Browser auto-
 * discovers any JournalEntry pack containing a document with `_id=MassEditMetaData`,
 * so the manual "Import → JSON" step the operator used to do disappears.
 *
 * Usage:
 *     node compile_preset_pack.mjs               # use default paths
 *     node compile_preset_pack.mjs SRC DST       # explicit src/dst
 */

// classic-level is provided by the sibling wh40k-rpg system's node_modules;
// no separate install needed for the cartography subdir.
import { readdirSync, readFileSync, rmSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const { ClassicLevel } = await import(resolve(HERE, '..', 'node_modules', 'classic-level', 'index.js'));

const srcDir = resolve(process.argv[2] ?? join(HERE, 'dh-cartography', 'packs-src', 'dh-presets-journals'));
const dstDir = resolve(process.argv[3] ?? join(HERE, 'dh-cartography', 'packs', 'dh-presets-journals'));

if (!existsSync(srcDir)) {
    console.error(`source dir not found: ${srcDir}`);
    process.exit(1);
}

if (existsSync(dstDir)) {
    rmSync(dstDir, { recursive: true, force: true });
}
mkdirSync(dstDir, { recursive: true });

const db = new ClassicLevel(dstDir, { valueEncoding: 'json' });
await db.open();

let count = 0;
try {
    for (const file of readdirSync(srcDir)) {
        if (!file.endsWith('.json')) continue;
        const doc = JSON.parse(readFileSync(join(srcDir, file), 'utf8'));
        if (!doc._id) {
            console.error(`skipping ${file}: missing _id`);
            continue;
        }
        await db.put(`!journal!${doc._id}`, doc);
        count += 1;
    }
} finally {
    await db.close();
}

console.log(`compiled ${count} JournalEntry docs → ${dstDir}`);
