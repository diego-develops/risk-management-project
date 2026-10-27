import os

import aws_cdk as cdk

from stack import REGION, OnboardingStack

app = cdk.App()
OnboardingStack(
    app,
    "OnboardingStack",
    # Every resource of this project must live in the project's assigned Region.
    env=cdk.Environment(account=os.environ["CDK_DEFAULT_ACCOUNT"], region=REGION),
)
app.synth()
