#!/usr/bin/env bash
set -euo pipefail

: "${STEALTHBENCH_AWS_VPC_ID:?set STEALTHBENCH_AWS_VPC_ID}"
: "${STEALTHBENCH_AWS_VPC_CIDR:?set STEALTHBENCH_AWS_VPC_CIDR}"
: "${STEALTHBENCH_AWS_SUBNET_ID:?set STEALTHBENCH_AWS_SUBNET_ID}"
: "${STEALTHBENCH_CONTROLLER_ROLE_NAME:?set STEALTHBENCH_CONTROLLER_ROLE_NAME}"
: "${STEALTHBENCH_CONTROLLER_SECURITY_GROUP_ID:?set STEALTHBENCH_CONTROLLER_SECURITY_GROUP_ID}"

REGION="${AWS_REGION:-us-west-2}"
STACK="${STEALTHBENCH_WINDOWS_STACK:-stealthbench-windows-endpoint}"

aws cloudformation deploy \
  --region "$REGION" \
  --stack-name "$STACK" \
  --template-file infra/aws/windows-endpoint.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    VpcId="$STEALTHBENCH_AWS_VPC_ID" \
    VpcCidr="$STEALTHBENCH_AWS_VPC_CIDR" \
    SubnetId="$STEALTHBENCH_AWS_SUBNET_ID" \
    ControllerRoleName="$STEALTHBENCH_CONTROLLER_ROLE_NAME" \
    ControllerUserName="${STEALTHBENCH_CONTROLLER_USER_NAME:-stealthbench-suite-runner}" \
    ControllerSecurityGroupId="$STEALTHBENCH_CONTROLLER_SECURITY_GROUP_ID"

INSTANCE_IDS=$(aws cloudformation describe-stacks \
  --region "$REGION" \
  --stack-name "$STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`InstanceIds`].OutputValue' \
  --output text)

echo "export STEALTHBENCH_WINDOWS_INSTANCE_IDS=$INSTANCE_IDS"
