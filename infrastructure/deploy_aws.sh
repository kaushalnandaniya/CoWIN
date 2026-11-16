#!/usr/bin/env bash
# =============================================================================
# IT457 Cloud Computing - CoWIN PoC AWS Automated Deployer & Manager
# Authored for: Kaushal Nandaniya (ID: 202303036) - AWS Cloud Infrastructure Lead
# =============================================================================

set -euo pipefail

REGION="ap-south-1"
STACK_NAME="cowin-poc-two-zone"
TEMPLATE_FILE="$(dirname "$0")/aws_cfn_cowin_two_zone.yaml"

# CloudFormation accepts at most 51,200 bytes inline via --template-body;
# larger templates must be uploaded to S3 and passed via --template-url.
# https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cloudformation-limits.html
TEMPLATE_INLINE_CAP_BYTES=51200

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

if ! command_exists aws; then
    echo "Error: AWS CLI is not installed or not in PATH."
    echo "Install it ('brew install awscli') and configure it with 'aws configure'."
    exit 1
fi

case "$1" in
    deploy)
        template_size=$(wc -c < "$TEMPLATE_FILE")
        if [ "$template_size" -gt "$TEMPLATE_INLINE_CAP_BYTES" ]; then
            echo "Error: $TEMPLATE_FILE is $template_size bytes, over the"
            echo "$TEMPLATE_INLINE_CAP_BYTES-byte inline template cap (--template-body)."
            echo "Shrink the template, or upload it to S3 and deploy with --template-url."
            exit 1
        fi

        # Each node fetches the application artifact from the repository at
        # boot. Pin the ref so the deploy is reproducible: default to the
        # checked-out HEAD when run from a clone, else the template default.
        APP_REPO_REF="${APP_REPO_REF:-}"
        if [ -z "$APP_REPO_REF" ] && command_exists git && \
               git -C "$(dirname "$0")/.." rev-parse HEAD >/dev/null 2>&1; then
            APP_REPO_REF=$(git -C "$(dirname "$0")/.." rev-parse HEAD)
        fi
        if [ -n "$APP_REPO_REF" ]; then
            echo "Application artifact ref: $APP_REPO_REF (pinned)"
            REF_PARAM="ParameterKey=AppRepoRef,ParameterValue=$APP_REPO_REF"
        else
            echo "Application artifact ref: template default (main)"
            REF_PARAM="ParameterKey=AppRepoRef,ParameterValue=main"
        fi

        # The template requires an API key for the /simulate/* endpoints so a
        # fresh deploy never exposes them unauthenticated. Note that the ALB
        # listener also denies /simulate/* at the edge; failover drills use
        # 'fail-zone-a' (EC2 stop), which needs no inbound access.
        COWIN_API_KEY="${COWIN_API_KEY:-}"
        if [ -z "$COWIN_API_KEY" ]; then
            COWIN_API_KEY=$(openssl rand -hex 24 2>/dev/null \
                || python3 -c 'import secrets; print(secrets.token_hex(24))')
            echo "Generated an ephemeral COWIN_API_KEY for the /simulate/* endpoints."
            echo "Save it if you need direct instance-level simulation: $COWIN_API_KEY"
        fi

        echo "Deploying CoWIN Two-Zone CloudFormation stack into $REGION..."
        aws cloudformation validate-template \
            --template-body "file://$TEMPLATE_FILE" \
            --region "$REGION" >/dev/null
        aws cloudformation create-stack \
            --stack-name "$STACK_NAME" \
            --template-body "file://$TEMPLATE_FILE" \
            --parameters ParameterKey=InstanceType,ParameterValue=t3.micro \
                         ParameterKey=COWINApiKey,ParameterValue="$COWIN_API_KEY" \
                         "$REF_PARAM" \
            --region "$REGION"

        echo "Waiting for stack creation to complete (this takes ~3-4 minutes)..."
        aws cloudformation wait stack-create-complete --stack-name "$STACK_NAME" --region "$REGION"
        echo "Stack deployment completed successfully."

        echo ""
        echo "Stack outputs:"
        aws cloudformation describe-stacks \
            --stack-name "$STACK_NAME" \
            --region "$REGION" \
            --query "Stacks[0].Outputs[*].[OutputKey,OutputValue]" \
            --output table
        ;;

    status)
        echo "Fetching target group health status in $REGION..."
        TG_ARN=$(aws cloudformation describe-stacks \
            --stack-name "$STACK_NAME" \
            --region "$REGION" \
            --query "Stacks[0].Outputs[?OutputKey=='TargetGroupArn'].OutputValue" \
            --output text)

        if [ -n "$TG_ARN" ]; then
            aws elbv2 describe-target-health --target-group-arn "$TG_ARN" --region "$REGION" --output table
        else
            echo "Error: Target Group ARN not found. Is the stack deployed?"
        fi
        ;;

    fail-zone-a)
        echo "Simulating AZ failure: stopping the instance in Zone A..."
        INST_A=$(aws cloudformation describe-stacks \
            --stack-name "$STACK_NAME" \
            --region "$REGION" \
            --query "Stacks[0].Outputs[?OutputKey=='InstanceAZoneAId'].OutputValue" \
            --output text)

        if [ -n "$INST_A" ]; then
            echo "Stopping EC2 instance: $INST_A"
            aws ec2 stop-instances --instance-ids "$INST_A" --region "$REGION"
            echo "Stop signal issued. Monitor ALB target health and run failover_benchmark.py."
        fi
        ;;

    recover-zone-a)
        echo "Restoring the instance in Zone A..."
        INST_A=$(aws cloudformation describe-stacks \
            --stack-name "$STACK_NAME" \
            --region "$REGION" \
            --query "Stacks[0].Outputs[?OutputKey=='InstanceAZoneAId'].OutputValue" \
            --output text)

        if [ -n "$INST_A" ]; then
            echo "Starting EC2 instance: $INST_A"
            aws ec2 start-instances --instance-ids "$INST_A" --region "$REGION"
            echo "Start signal issued. The instance re-registers with the ALB target group once healthy."
        fi
        ;;

    destroy)
        echo "Deleting CloudFormation stack: $STACK_NAME..."
        aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION"
        echo "Waiting for stack deletion to complete..."
        aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION"
        echo "Stack successfully deleted. No recurring AWS charges remain."
        ;;

    *)
        echo "Usage: $0 {deploy|status|fail-zone-a|recover-zone-a|destroy}"
        exit 1
        ;;
esac
