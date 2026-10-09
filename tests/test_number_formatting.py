"""Display numbers stay readable without changing numeric API/input values."""
import shutil
import subprocess
import unittest
from pathlib import Path
from test_upgrade import app


class NumberFormattingTests(unittest.TestCase):
    def test_server_costs_use_commas_and_preserve_fractional_amounts(self):
        self.assertEqual(app.fmt_cost({'money':1000000}), '1,000,000'+app.RES_EMOJI['money'])
        self.assertEqual(app.fmt_cost({'wood':1234.5}), '1,234.5'+app.RES_EMOJI['wood'])

    @unittest.skipUnless(shutil.which('node'), 'Node is required to check browser helpers')
    def test_browser_balances_population_costs_and_invalid_values(self):
        script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const source = fs.readFileSync('static/legacy-client.js', 'utf8');
const helpers = source.split(/\r?\n/).filter(line => /^(function fmtN\(|function fmtPop\(|const fmtCost=)/.test(line)).join('\n');
const context = vm.createContext({resIcon: {money: 'money'}});
vm.runInContext(helpers, context);
for (const [input, expected] of [[1000000,'1,000,000'],[9999,'9,999'],[-1234567,'-1,234,567'],[0,'0'],[Infinity,'0'],[NaN,'0']]) {
  assert.equal(context.fmtN(input), expected);
  assert.equal(context.fmtPop(input), expected);
}
assert.equal(context.fmtN(1234567.25, 2), '1,234,567.25');
assert.equal(context.fmtN(999.75), '999.75');
assert.equal(vm.runInContext('fmtCost({money: 1234567.25})', context), '1,234,567.25money');
'''
        result = subprocess.run([shutil.which('node'), '-e', script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
