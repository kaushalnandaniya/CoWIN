#!/usr/bin/env bash
# =============================================================================
# IT457 Cloud Computing - CoWIN PoC AWS Automated Deployer & Manager
# Authored for: Kaushal Nandaniya (ID: 202303036) - AWS Cloud Infrastructure Lead
# =============================================================================

set -e

REGION="ap-south-1"
STACK_NAME="cowin-poc-two-zone"
TEMPLATE_FILE="$(dirname "$0")/aws_cfn_cowin_two_zone.yaml"

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

if ! command_exists aws; then
    echo "❌ Error: AWS CLI is not installed or not in PATH."
    echo "   Please install it: 'brew install awscli' and configure with 'aws configure'."
    exit 1
fi

case "$1" in
    deploy)
        echo "🚀 Deploying CoWIN Two-Zone CloudFormation Stack into $REGION..."
        aws cloudformation create-stack \
            --stack-name "$STACK_NAME" \
            --template-body "file://$TEMPLATE_FILE" \
            --parameters ParameterKey=InstanceType,ParameterValue=t3.micro \
            --region "$REGION"
        
        echo "⏳ Waiting for stack creation to complete (this takes ~3-4 minutes)..."
        aws cloudformation wait stack-create-complete --stack-name "$STACK_NAME" --region "$REGION"
        echo "✅ Stack deployment completed successfully!"
        
        echo -e "\n📋 Stack Outputs:"
        aws cloudformation describe-stacks \
            --stack-name "$STACK_NAME" \
            --region "$REGION" \
            --query "Stacks[0].Outputs[*].[OutputKey,OutputValue]" \
            --output table
        ;;

    status)
        echo "📊 Fetching Target Group Health Status in $REGION..."
        TG_ARN=$(aws cloudformation describe-stacks \
            --stack-name "$STACK_NAME" \
            --region "$REGION" \
            --query "Stacks[0].Outputs[?OutputKey=='TargetGroupArn'].OutputValue" \
            --output text)
        
        if [ -n "$TG_ARN" ]; then
            aws elbv2 describe-target-health --target-group-arn "$TG_ARN" --region "$REGION" --output table
        else
            echo "❌ Target Group ARN not found. Is the stack deployed?"
        fi
        ;;

    fail-zone-a)
        echo "⚠️  Simulating AZ Failure: Stopping Instance in Zone A..."
        INST_A=$(aws cloudformation describe-stacks \
            --stack-name "$STACK_NAME" \
            --region "$REGION" \
            --query "Stacks[0].Outputs[?OutputKey=='InstanceAZoneAId'].OutputValue" \
            --output text)
        
        if [ -n "$INST_A" ]; then
            echo "🛑 Stopping EC2 instance: $INST_A"
            aws ec2 stop-instances --instance-ids "$INST_A" --region "$REGION"
            echo "✅ Stop signal issued. Monitor ALB target health and run failover_benchmark.py!"
        fi
        ;;

    recover-zone-a)
        echo "🔄 Restoring Instance in Zone A..."
        INST_A=$(aws cloudformation describe-stacks \
            --stack-name "$STACK_NAME" \
            --region "$REGION" \
            --query "Stacks[0].Outputs[?OutputKey=='InstanceAZoneAId'].OutputValue" \
            --output text)
        
        if [ -n "$INST_A" ]; then
            echo "▶️  Starting EC2 instance: $INST_A"
            aws ec2 start-instances --instance-ids "$INST_A" --region "$REGION"
            echo "✅ Start signal issued. Instance will re-register with ALB Target Group once healthy."
        fi
        ;;

    destroy)
        echo "🧨 Deleting CloudFormation Stack: $STACK_NAME..."
        aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION"
        echo "⏳ Waiting for stack deletion to complete..."
        aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION"
        echo "✅ Stack successfully deleted. No recurring AWS charges remain."
        ;;

    *)
        echo "Usage: $0 {deploy|status|fail-zone-a|recover-zone-a|destroy}"
        exit 1
        ;;
esac

