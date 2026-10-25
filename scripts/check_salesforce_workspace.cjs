/* Compile the wrapper templates with Salesforce's official open-source LWC compiler. */
const fs = require('node:fs');
const path = require('node:path');

(async () => {
    const compilerModule = process.argv[2] || '@lwc/compiler';
    const { transformSync } = await import(require.resolve(compilerModule));
    const folder = path.join(__dirname, 'salesforce_workspace');
    const name = 'lifeAfterCodePreview';
    for (const extension of ['js', 'html', 'css']) {
        let source = fs.readFileSync(path.join(folder, 'workspace.' + extension), 'utf8');
        source = source.replace('__FRONTEND_URL__', JSON.stringify('https://mim.example/mim'))
            .replace('__RECORD_IMPORT__', "import readRecords from '@salesforce/apex/LifeAfterCodeReaderPreview.readRecords';")
            .replaceAll('__RECORD_READER__', 'readRecords')
            .replace('__BRIDGE_ENABLED__', 'true').replace('__OBJECT_OPTIONS__', '[]');
        const result = transformSync(source, name + '.' + extension, {
            namespace: 'c', name, apiVersion: 65, enableLightningWebSecurityTransforms: true,
        });
        if (!result.code || result.warnings?.length) {
            throw new Error('LWC compilation needs attention: ' + JSON.stringify(result.warnings));
        }
        console.log('Workspace ' + extension + ': compiled without warnings');
    }
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
