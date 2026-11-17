.class public final Lcom/box/app/cfg/FormActivity;
.super Lcom/box/app/cfg/CfgBaseActivity;
.source "Activities.kt"


# annotations
.annotation system Ldalvik/annotation/SourceDebugExtension;
    value = "SMAP\nActivities.kt\nKotlin\n*S Kotlin\n*F\n+ 1 Activities.kt\ncom/box/app/cfg/FormActivity\n+ 2 fake.kt\nkotlin/jvm/internal/FakeKt\n*L\n1#1,194:1\n1#2:195\n*E\n"
.end annotation

.annotation runtime Lkotlin/Metadata;
    d1 = {
        "\u0000(\n\u0002\u0018\u0002\n\u0002\u0018\u0002\n\u0002\u0008\u0003\n\u0002\u0018\u0002\n\u0000\n\u0002\u0010\u0000\n\u0000\n\u0002\u0010\u0002\n\u0002\u0008\u0002\n\u0002\u0010\u000e\n\u0002\u0008\u0003\u0018\u00002\u00020\u0001B\u0007\u00a2\u0006\u0004\u0008\u0002\u0010\u0003J \u0010\u0008\u001a\u00020\t2\u0006\u0010\n\u001a\u00020\u00072\u0006\u0010\u000b\u001a\u00020\u000c2\u0006\u0010\r\u001a\u00020\u000cH\u0016J\u0008\u0010\u000e\u001a\u00020\tH\u0014J\u0008\u0010\u000f\u001a\u00020\tH\u0016R\u0010\u0010\u0004\u001a\u0004\u0018\u00010\u0005X\u0082\u000e\u00a2\u0006\u0002\n\u0000R\u0010\u0010\u0006\u001a\u0004\u0018\u00010\u0007X\u0082\u000e\u00a2\u0006\u0002\n\u0000"
    }
    d2 = {
        "Lcom/box/app/cfg/FormActivity;",
        "Lcom/box/app/cfg/CfgBaseActivity;",
        "<init>",
        "()V",
        "ui",
        "Lcom/box/app/cfg/FormUi;",
        "editorToken",
        "",
        "build",
        "",
        "token",
        "text",
        "",
        "path",
        "onResume",
        "onBackAction"
    }
    k = 0x1
    mv = {
        0x2,
        0x4,
        0x0
    }
    xi = 0x30
.end annotation

.annotation build Lkotlin/jvm/internal/SourceDebugExtension;
    value = {
        "SMAP\nActivities.kt\nKotlin\n*S Kotlin\n*F\n+ 1 Activities.kt\ncom/box/app/cfg/FormActivity\n+ 2 fake.kt\nkotlin/jvm/internal/FakeKt\n*L\n1#1,194:1\n1#2:195\n*E\n"
    }
.end annotation


# instance fields
.field private editorToken:Ljava/lang/Object;
    .annotation build Lorg/jetbrains/annotations/Nullable;
    .end annotation
.end field

.field private ui:Lcom/box/app/cfg/FormUi;
    .annotation build Lorg/jetbrains/annotations/Nullable;
    .end annotation
.end field


# direct methods


# virtual methods

.method public constructor <init>()V
    .registers 1

    .line 157
    invoke-direct {p0}, Lcom/box/app/cfg/CfgBaseActivity;-><init>()V

    return-void
.end method

.method public build(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;)V
    .registers 12
    .param p1    # Ljava/lang/Object;
        .annotation build Lorg/jetbrains/annotations/NotNull;
        .end annotation
    .end param
    .param p2    # Ljava/lang/String;
        .annotation build Lorg/jetbrains/annotations/NotNull;
        .end annotation
    .end param
    .param p3    # Ljava/lang/String;
        .annotation build Lorg/jetbrains/annotations/NotNull;
        .end annotation
    .end param

    .line 162
    iput-object p1, p0, Lcom/box/app/cfg/FormActivity;->editorToken:Ljava/lang/Object;

    .line 163
    new-instance v0, Ljava/io/File;

    invoke-direct {v0, p3}, Ljava/io/File;-><init>(Ljava/lang/String;)V

    .line 164
    new-instance p3, Lcom/box/app/cfg/FormUi;

    move-object v2, p0

    check-cast v2, Landroid/app/Activity;

    invoke-virtual {p0}, Lcom/box/app/cfg/FormActivity;->getSc()Lcom/box/app/cfg/Scaffold;

    move-result-object v3

    invoke-virtual {v0}, Ljava/io/File;->getName()Ljava/lang/String;

    move-result-object v5

    invoke-virtual {v0}, Ljava/io/File;->getParent()Ljava/lang/String;

    move-result-object v6

    new-instance v0, Lcom/box/app/cfg/FormActivity$build$1;

    invoke-direct {v0, p1}, Lcom/box/app/cfg/FormActivity$build$1;-><init>(Ljava/lang/Object;)V

    move-object v7, v0

    check-cast v7, Lkotlin/jvm/functions/Function1;

    move-object v1, p3

    move-object v4, p2

    invoke-direct/range {v1 .. v7}, Lcom/box/app/cfg/FormUi;-><init>(Landroid/app/Activity;Lcom/box/app/cfg/Scaffold;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Lkotlin/jvm/functions/Function1;)V

    const/4 p1, 0x0

    invoke-virtual {p3, p1}, Lcom/box/app/cfg/FormUi;->render(Z)V

    iput-object p3, p0, Lcom/box/app/cfg/FormActivity;->ui:Lcom/box/app/cfg/FormUi;

    return-void
.end method

.method public onBackAction()V
    .registers 2

    .line 175
    iget-object v0, p0, Lcom/box/app/cfg/FormActivity;->ui:Lcom/box/app/cfg/FormUi;

    if-eqz v0, :cond_a

    .line 176
    invoke-virtual {v0}, Lcom/box/app/cfg/FormUi;->pop()Z

    move-result v0

    if-nez v0, :cond_d

    :cond_a
    invoke-virtual {p0}, Lcom/box/app/cfg/FormActivity;->finish()V

    :cond_d
    return-void
.end method

.method protected onResume()V
    .registers 2

    .line 168
    invoke-super {p0}, Lcom/box/app/cfg/CfgBaseActivity;->onResume()V

    .line 169
    iget-object v0, p0, Lcom/box/app/cfg/FormActivity;->editorToken:Ljava/lang/Object;

    if-nez v0, :cond_8

    return-void

    .line 170
    :cond_8
    invoke-static {v0}, Lcom/box/app/cfg/CfgGlue;->getText(Ljava/lang/Object;)Ljava/lang/String;

    move-result-object v0

    if-nez v0, :cond_f

    return-void

    .line 171
    :cond_f
    iget-object p0, p0, Lcom/box/app/cfg/FormActivity;->ui:Lcom/box/app/cfg/FormUi;

    if-eqz p0, :cond_16

    invoke-virtual {p0, v0}, Lcom/box/app/cfg/FormUi;->refreshFromEditor(Ljava/lang/String;)V

    :cond_16
    return-void
.end method
