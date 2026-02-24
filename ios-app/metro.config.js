const fs = require('fs');
const path = require('path');
const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);
const defaultResolveRequest = config.resolver.resolveRequest;

config.resolver.resolveRequest = (context, moduleName, platform) => {
  const origin = context.originModulePath || '';

  // Work around intermittent Metro resolution failures for mathjax-full internals
  // used by react-native-math-view (e.g. "../../../core/MmlTree/OperatorDictionary.js").
  if (
    origin.includes(`${path.sep}node_modules${path.sep}mathjax-full${path.sep}js${path.sep}input${path.sep}`) &&
    moduleName.startsWith('../../../')
  ) {
    const candidate = path.join(
      __dirname,
      'node_modules',
      'mathjax-full',
      'js',
      moduleName.slice('../../../'.length),
    );

    if (fs.existsSync(candidate)) {
      return { filePath: candidate, type: 'sourceFile' };
    }
  }

  if (typeof defaultResolveRequest === 'function') {
    return defaultResolveRequest(context, moduleName, platform);
  }
  return context.resolveRequest(context, moduleName, platform);
};

module.exports = config;
