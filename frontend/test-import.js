// Test if FitnessSection can be imported
import('./src/components/fitness/FitnessSection.tsx')
  .then(m => {
    console.log('✓ SUCCESS: FitnessSection imported');
    console.log('Default export:', m.default);
    console.log('All exports:', Object.keys(m));
  })
  .catch(e => {
    console.error('✗ ERROR: Failed to import FitnessSection');
    console.error(e.message);
    console.error(e.stack);
  });
