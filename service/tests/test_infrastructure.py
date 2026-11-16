"""Stdlib structural guards, not an AWS deployment/change-set simulator.

cfn-lint is run separately for the CloudFormation schema. These tests guard
our lifecycle wiring, rendered bootstrap shell, and documented tunnel ports.
"""
from pathlib import Path
import re
import shutil
import subprocess
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = (ROOT / "infrastructure/aws_cfn_cowin_two_zone.yaml").read_text()


def resource(name):
    match = re.search(r"^  " + name + r":\n(.*?)(?=^  [A-Za-z][A-Za-z0-9]*:|^Outputs:|\Z)",
                      TEMPLATE, re.M | re.S)
    if match is None:
        raise AssertionError("Missing resource: " + name)
    return match.group(1)


def bootstrap(letter):
    block = resource("BootstrapZone" + letter)
    return textwrap.dedent(block.split("Fn::Base64: !Sub |\n", 1)[1])


class TestInfrastructureContracts(unittest.TestCase):
    def test_versions_drive_replacement_instead_of_userdata_restart(self):
        for letter in ("A", "B"):
            with self.subTest(zone=letter):
                node = resource("InstanceZone" + letter)
                self.assertNotIn("UserData:", node)
                self.assertIn("LaunchTemplateId: !Ref BootstrapZone" + letter, node)
                self.assertIn("Version: !GetAtt BootstrapZone" + letter +
                              ".LatestVersionNumber", node)
                self.assertIn("Type: AWS::EC2::LaunchTemplate",
                              resource("BootstrapZone" + letter))

    def test_both_ip_changes_and_artifact_ref_change_both_bootstraps(self):
        values = {"ZoneAPrivateIp": "10.0.1.150", "ZoneBPrivateIp": "10.0.2.150",
                  "AppRepoOwner": "example", "AppRepoName": "CoWIN",
                  "AppRepoRef": "old-ref"}
        def render(script, params):
            for name, value in params.items():
                script = script.replace("${" + name + "}", value)
            return script
        for letter in ("A", "B"):
            script = bootstrap(letter)
            original = render(script, values)
            for parameter in ("ZoneAPrivateIp", "ZoneBPrivateIp", "AppRepoRef"):
                with self.subTest(zone=letter, parameter=parameter):
                    changed = dict(values, **{parameter: "changed"})
                    self.assertNotEqual(original, render(script, changed))
            peer = "B" if letter == "A" else "A"
            self.assertIn("COWIN_PEER_URL=http://${Zone" + peer +
                          "PrivateIp}:8080", script)
            self.assertIn("COWIN_ZONE_LETTER=" + letter.lower(), script)
            self.assertNotRegex(script, r"(?m)^\s*COWIN_API_KEY=")

    @unittest.skipUnless(shutil.which("bash"), "bash required for shell syntax")
    def test_bootstrap_shell_syntax(self):
        for letter in ("A", "B"):
            result = subprocess.run(["bash", "-n"], input=bootstrap(letter),
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_runbooks_include_all_three_loopback_forwards(self):
        for path in ("service/README.md", "infrastructure/deploy_aws.sh"):
            contents = (ROOT / path).read_text()
            self.assertIn("127.0.0.1:8080:<ALB DNS name>:80", contents)
            self.assertIn("127.0.0.1:8081:localhost:8080", contents)
            self.assertIn("127.0.0.1:8082:localhost:8080", contents)
            self.assertIn("ALB=http://localhost:8080", contents)

    def test_edge_deny_and_scoped_ssh_remain(self):
        self.assertIn("- /simulate/*", resource("ALBSimulateDenyRule"))
        self.assertIn("StatusCode: '403'", resource("ALBSimulateDenyRule"))
        group = resource("InstanceSecurityGroup")
        self.assertIn("CidrIp: !Ref OperatorSshCidr", group)
        for letter in ("A", "B"):
            self.assertIn("KeyName: !Ref OperatorKeyPair",
                          resource("InstanceZone" + letter))


if __name__ == "__main__":
    unittest.main()
