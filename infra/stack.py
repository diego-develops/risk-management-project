from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigateway as apigw,
    aws_bedrock as bedrock,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_s3vectors as s3vectors,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct

REGION = "us-east-2"
MODEL_ID = "amazon.nova-lite-v1:0"  # on-demand in us-east-2; no cross-Region inference profile
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024

ROOT = Path(__file__).resolve().parent.parent


class OnboardingStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        foundation_model_arn = lambda model_id: f"arn:aws:bedrock:{self.region}::foundation-model/{model_id}"  # noqa: E731

        # ---- Policy documents (KB source) -------------------------------------------------
        policies_bucket = s3.Bucket(
            self, "PoliciesBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        s3deploy.BucketDeployment(
            self, "DeployPolicies",
            sources=[s3deploy.Source.asset(str(ROOT / "policies"))],
            destination_bucket=policies_bucket,
        )

        # ---- Vector store (S3 Vectors) ----------------------------------------------------
        vector_bucket = s3vectors.CfnVectorBucket(self, "VectorBucket")
        vector_index = s3vectors.CfnIndex(
            self, "VectorIndex",
            vector_bucket_arn=vector_bucket.attr_vector_bucket_arn,
            data_type="float32",
            dimension=EMBEDDING_DIMENSIONS,
            distance_metric="cosine",
            # Bedrock stores the chunk text in this key; it must not be filterable metadata.
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=["AMAZON_BEDROCK_TEXT"],
            ),
        )

        # ---- Knowledge Base ---------------------------------------------------------------
        kb_role = iam.Role(
            self, "KnowledgeBaseRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/*"},
                },
            ),
        )
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"], resources=[foundation_model_arn(EMBEDDING_MODEL_ID)],
        ))
        policies_bucket.grant_read(kb_role)
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors",
                "s3vectors:QueryVectors", "s3vectors:GetIndex",
            ],
            resources=[vector_index.attr_index_arn],
        ))

        knowledge_base = bedrock.CfnKnowledgeBase(
            self, "KnowledgeBase",
            name="onboarding-policies",
            role_arn=kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=foundation_model_arn(EMBEDDING_MODEL_ID),
                    embedding_model_configuration=bedrock.CfnKnowledgeBase.EmbeddingModelConfigurationProperty(
                        bedrock_embedding_model_configuration=bedrock.CfnKnowledgeBase.BedrockEmbeddingModelConfigurationProperty(
                            dimensions=EMBEDDING_DIMENSIONS, embedding_data_type="FLOAT32",
                        ),
                    ),
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    index_arn=vector_index.attr_index_arn,
                ),
            ),
        )
        knowledge_base.node.add_dependency(kb_role)  # wait for the role's policy to exist

        data_source = bedrock.CfnDataSource(
            self, "PoliciesDataSource",
            knowledge_base_id=knowledge_base.attr_knowledge_base_id,
            name="policies-s3",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=policies_bucket.bucket_arn,
                ),
            ),
            # Short markdown policies: fixed-size chunks are enough. Cannot be changed later.
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy="FIXED_SIZE",
                    fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                        max_tokens=300, overlap_percentage=20,
                    ),
                ),
            ),
        )

        # ---- Guardrail --------------------------------------------------------------------
        # Classic tier on purpose: the Standard tier requires cross-Region inference.
        guardrail = bedrock.CfnGuardrail(
            self, "Guardrail",
            name="onboarding-guardrail",
            blocked_input_messaging="No podemos procesar esta solicitud.",
            blocked_outputs_messaging="No podemos mostrar esta respuesta.",
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=[
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type="PROMPT_ATTACK", input_strength="HIGH", output_strength="NONE",
                    ),
                    *[
                        bedrock.CfnGuardrail.ContentFilterConfigProperty(
                            type=kind, input_strength="MEDIUM", output_strength="MEDIUM",
                        )
                        for kind in ("HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT")
                    ],
                ],
            ),
            # The customer's own first name is intentionally NOT filtered: it is the greeting.
            sensitive_information_policy_config=bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty(
                pii_entities_config=[
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(type="CREDIT_DEBIT_CARD_NUMBER", action="BLOCK"),
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(type="EMAIL", action="ANONYMIZE"),
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(type="PHONE", action="ANONYMIZE"),
                ],
            ),
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(
                topics_config=[
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="risk-list-disclosure",
                        type="DENY",
                        definition=(
                            "Revelar a un cliente que figura en listas de riesgo, su nivel de riesgo, "
                            "o los motivos internos de un escalamiento o rechazo."
                        ),
                        examples=[
                            "Su nombre coincide con una lista de personas expuestas políticamente.",
                            "Su solicitud fue escalada porque su nivel de riesgo es alto.",
                        ],
                    ),
                ],
            ),
        )
        guardrail_version = bedrock.CfnGuardrailVersion(
            self, "GuardrailVersion",
            guardrail_identifier=guardrail.attr_guardrail_id,
            description="onboarding-v1",
        )

        # ---- Lambda (Agent0 + agents) -----------------------------------------------------
        log_group = logs.LogGroup(
            self, "FunctionLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        function = lambda_.Function(
            self, "OnboardingFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="onboarding.handler.handler",
            code=lambda_.Code.from_asset(str(ROOT / "build" / "lambda")),
            timeout=Duration.seconds(25),  # below API Gateway's 29 s hard limit
            memory_size=512,
            log_group=log_group,
            environment={
                "MODEL_ID": MODEL_ID,
                "GUARDRAIL_ID": guardrail.attr_guardrail_id,
                "GUARDRAIL_VERSION": guardrail_version.attr_version,
                "KB_ID": knowledge_base.attr_knowledge_base_id,
            },
        )
        function.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"], resources=[foundation_model_arn(MODEL_ID)],
        ))
        function.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:ApplyGuardrail"], resources=[guardrail.attr_guardrail_arn],
        ))
        function.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:Retrieve"], resources=[knowledge_base.attr_knowledge_base_arn],
        ))

        # ---- API Gateway ------------------------------------------------------------------
        api = apigw.RestApi(
            self, "Api",
            rest_api_name="onboarding-api",
            endpoint_types=[apigw.EndpointType.REGIONAL],
            deploy_options=apigw.StageOptions(
                stage_name="prod", throttling_rate_limit=5, throttling_burst_limit=10,
            ),
        )
        start = api.root.add_resource("api").add_resource("v1").add_resource("onboarding").add_resource("start")
        start.add_method("POST", apigw.LambdaIntegration(function), api_key_required=True)

        # Each call can reach Bedrock, so the endpoint needs a key and a hard daily cap.
        usage_plan = api.add_usage_plan(
            "UsagePlan",
            throttle=apigw.ThrottleSettings(rate_limit=5, burst_limit=10),
            quota=apigw.QuotaSettings(limit=500, period=apigw.Period.DAY),
        )
        # The key lives in Secrets Manager and is injected by CloudFront, so it is never
        # in the page or the browser. `unsafe_unwrap` only yields a CloudFormation dynamic
        # reference ({{resolve:secretsmanager:...}}), not the plaintext.
        api_key_secret = secretsmanager.Secret(
            self, "ApiKeySecret",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                exclude_punctuation=True, password_length=40,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )
        api_key_value = api_key_secret.secret_value.unsafe_unwrap()
        api_key = api.add_api_key("ApiKey", value=api_key_value)
        usage_plan.add_api_key(api_key)
        usage_plan.add_api_stage(stage=api.deployment_stage)

        # ---- Portal: private S3 site behind CloudFront, /api/* proxied to API Gateway ------
        site_bucket = s3.Bucket(
            self, "SiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        security_headers = cloudfront.ResponseHeadersPolicy(
            self, "SecurityHeaders",
            security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                content_security_policy=cloudfront.ResponseHeadersContentSecurityPolicy(
                    content_security_policy=(
                        "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
                        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
                    ),
                    override=True,
                ),
                content_type_options=cloudfront.ResponseHeadersContentTypeOptions(override=True),
                frame_options=cloudfront.ResponseHeadersFrameOptions(
                    frame_option=cloudfront.HeadersFrameOption.DENY, override=True,
                ),
                referrer_policy=cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=cloudfront.HeadersReferrerPolicy.NO_REFERRER, override=True,
                ),
                strict_transport_security=cloudfront.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=Duration.days(365), include_subdomains=True, override=True,
                ),
            ),
        )
        distribution = cloudfront.Distribution(
            self, "PortalDistribution",
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=security_headers,
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origins.HttpOrigin(
                        f"{api.rest_api_id}.execute-api.{self.region}.amazonaws.com",
                        origin_path=f"/{api.deployment_stage.stage_name}",
                        protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
                        # CloudFront overwrites any x-api-key the viewer sends.
                        custom_headers={"x-api-key": api_key_value},
                    ),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    response_headers_policy=security_headers,
                ),
            },
        )
        s3deploy.BucketDeployment(
            self, "DeployPortal",
            sources=[s3deploy.Source.asset(str(ROOT / "portal"))],
            destination_bucket=site_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        CfnOutput(self, "PortalUrl", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "ApiUrl", value=api.url_for_path("/api/v1/onboarding/start"))
        CfnOutput(self, "ApiKeyId", value=api_key.key_id)
        CfnOutput(self, "ApiKeySecretName", value=api_key_secret.secret_name)
        CfnOutput(self, "KnowledgeBaseId", value=knowledge_base.attr_knowledge_base_id)
        CfnOutput(self, "DataSourceId", value=data_source.attr_data_source_id)
        CfnOutput(self, "GuardrailId", value=guardrail.attr_guardrail_id)
