#!/usr/bin/env bash
# =============================================================================
# IT457 Cloud Computing - CoWIN PoC AWS Automated Deployer & Manager
# Deploys and manages the two-zone CloudFormation stack (see README.md for ownership)
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

        # Operator access is required: /simulate drills run over SSH
        # tunnels, and the API key is set over SSH after boot (never in
        # UserData, where the console could read it). Pass the key pair
        # and the single operator IP.
        KEY_PAIR_NAME="${COWIN_KEY_PAIR:-}"
        SSH_CIDR="${COWIN_SSH_CIDR:-}"
        if [ -z "$KEY_PAIR_NAME" ] || [ -z "$SSH_CIDR" ]; then
            echo "Error: set COWIN_KEY_PAIR (existing EC2 key pair name) and"
            echo "COWIN_SSH_CIDR (your operator IP in /32 form, e.g. 203.0.113.10/32)."
            echo "These grant operator SSH access for drills; port 22 opens only to that IP."
            exit 1
        fi

        echo "Deploying CoWIN Two-Zone CloudFormation stack into $REGION..."
        aws cloudformation validate-template \
            --template-body "file://$TEMPLATE_FILE" \
            --region "$REGION" >/dev/null
        aws cloudformation create-stack \
            --stack-name "$STACK_NAME" \
            --template-body "file://$TEMPLATE_FILE" \
            --parameters ParameterKey=InstanceType,ParameterValue=t3.micro \
                         ParameterKey=OperatorKeyPair,ParameterValue="$KEY_PAIR_NAME" \
                         ParameterKey=OperatorSshCidr,ParameterValue="$SSH_CIDR" \
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

        cat <<'RUNBOOK'

Operator post-deploy steps (the /simulate drill key is never in UserData):
  1. Pick an operator key (16+ chars), keep it in a password manager.
  2. On BOTH nodes, over SSH (ASCII letters/digits/-/_ key):
       sudo chmod 600 /etc/default/cowin-lookup
       read -rsp 'Drill key: ' COWIN_API_KEY; printf '\n'
       printf 'COWIN_API_KEY=%s\n' "$COWIN_API_KEY" | sudo tee -a /etc/default/cowin-lookup >/dev/null
       unset COWIN_API_KEY
       sudo systemctl restart cowin
  3. Terminal 1 (replace <ALB DNS name> with LoadBalancerDNSName output):
       ssh -N -o ExitOnForwardFailure=yes \
         -L 127.0.0.1:8080:<ALB DNS name>:80 \
         -L 127.0.0.1:8081:localhost:8080 ec2-user@<zone A public IP>
     Terminal 2:
       ssh -N -o ExitOnForwardFailure=yes \
         -L 127.0.0.1:8082:localhost:8080 ec2-user@<zone B public IP>
     Add -i <private-key-file> if needed. Open http://localhost:8081/admin/
     Apply ALB=http://localhost:8080 A=http://localhost:8081 B=http://localhost:8082.
     Check all endpoints BEFORE entering the key. Keep both SSH sessions up.
     Browser-to-AWS traffic uses SSH; the ALB forward/peer probes use HTTP
     inside AWS. Never enter the key on the public site or send it in chat.
  4. This helper creates stacks; it does not update them. Replacing updates
     require TWO fresh free private IPs and a reviewed change set replacing
     BOTH nodes. Both bootstraps refresh both peer URLs via launch templates.
     Reinstall the key on BOTH replacement nodes and reopen all forwards.
     See service/README.md for migration, maintenance and rollback checks.

RUNBOOK
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
