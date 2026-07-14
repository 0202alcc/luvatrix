package com.luvatrix.app

internal class SynchronizedLazyResource<T>(initializer: () -> T) {
    private val delegate = lazy(LazyThreadSafetyMode.SYNCHRONIZED, initializer)

    fun get(): T = delegate.value

    fun isInitialized(): Boolean = delegate.isInitialized()
}

internal data class FullScenePresentation(
    val sceneJson: String,
    val revision: Int,
    val logicalWidth: Int,
    val logicalHeight: Int,
    val presentationMode: String,
    internal val generation: Long,
)

internal data class SceneTransformPresentation(
    val revision: Int,
    val contentOffsetX: Double,
    val contentOffsetY: Double,
    internal val generation: Long,
)

internal data class SceneReplayRequest(
    val scene: FullScenePresentation,
    val transform: SceneTransformPresentation?,
    internal val surfaceGeneration: Long,
)

internal data class SceneTransformRequest(
    val transform: SceneTransformPresentation,
    internal val sceneGeneration: Long,
    internal val surfaceGeneration: Long,
)

internal data class SceneDisplayState(
    val scene: FullScenePresentation,
    val transform: SceneTransformPresentation?,
    val nativeBackground: Boolean,
)

internal class SceneReplayCoordinator {
    private val lock = Any()
    private var nextSceneGeneration = 0L
    private var nextTransformGeneration = 0L
    private var currentSurfaceGeneration = 0L
    private var attachedSurfaceGeneration: Long? = null
    private var latestScene: FullScenePresentation? = null
    private var latestTransform: SceneTransformPresentation? = null
    private var nativeSceneGeneration: Long? = null
    private var nativeTransformGeneration: Long? = null

    fun retainFullScene(
        sceneJson: String,
        revision: Int,
        logicalWidth: Int,
        logicalHeight: Int,
        presentationMode: String,
    ): FullScenePresentation = synchronized(lock) {
        nextSceneGeneration += 1L
        FullScenePresentation(
            sceneJson = sceneJson,
            revision = revision,
            logicalWidth = logicalWidth,
            logicalHeight = logicalHeight,
            presentationMode = presentationMode,
            generation = nextSceneGeneration,
        ).also {
            latestScene = it
            latestTransform = null
            nativeSceneGeneration = null
            nativeTransformGeneration = null
        }
    }

    fun retainTransform(
        revision: Int,
        contentOffsetX: Double,
        contentOffsetY: Double,
    ): SceneTransformPresentation? = synchronized(lock) {
        if (latestScene == null) return@synchronized null
        nextTransformGeneration += 1L
        SceneTransformPresentation(
            revision = revision,
            contentOffsetX = contentOffsetX,
            contentOffsetY = contentOffsetY,
            generation = nextTransformGeneration,
        ).also { latestTransform = it }
    }

    fun surfaceChanging(generation: Long) = synchronized(lock) {
        if (generation < currentSurfaceGeneration) return@synchronized
        currentSurfaceGeneration = generation
        attachedSurfaceGeneration = null
        nativeSceneGeneration = null
        nativeTransformGeneration = null
    }

    fun surfaceAttached(generation: Long): SceneReplayRequest? = synchronized(lock) {
        if (generation != currentSurfaceGeneration) return@synchronized null
        attachedSurfaceGeneration = generation
        nativeSceneGeneration = null
        nativeTransformGeneration = null
        latestScene?.let { SceneReplayRequest(it, latestTransform, generation) }
    }

    fun presentationRequest(scene: FullScenePresentation): SceneReplayRequest? = synchronized(lock) {
        val surfaceGeneration = attachedSurfaceGeneration ?: return@synchronized null
        if (latestScene?.generation != scene.generation) return@synchronized null
        SceneReplayRequest(scene, latestTransform, surfaceGeneration)
    }

    fun transformRequest(transform: SceneTransformPresentation): SceneTransformRequest? = synchronized(lock) {
        val scene = latestScene ?: return@synchronized null
        val surfaceGeneration = attachedSurfaceGeneration ?: return@synchronized null
        if (latestTransform?.generation != transform.generation) return@synchronized null
        if (nativeSceneGeneration != scene.generation) return@synchronized null
        SceneTransformRequest(transform, scene.generation, surfaceGeneration)
    }

    fun isCurrent(request: SceneReplayRequest): Boolean = synchronized(lock) {
        isCurrentLocked(request)
    }

    fun isCurrent(request: SceneTransformRequest): Boolean = synchronized(lock) {
        isCurrentLocked(request)
    }

    fun markPresented(request: SceneReplayRequest, accepted: Boolean): Boolean = synchronized(lock) {
        val isCurrent = isCurrentLocked(request)
        if (!isCurrent || !accepted) {
            if (isCurrent) {
                nativeSceneGeneration = null
                nativeTransformGeneration = null
            }
            return@synchronized false
        }
        nativeSceneGeneration = request.scene.generation
        nativeTransformGeneration = request.transform?.generation
        true
    }

    fun markTransformPresented(request: SceneTransformRequest, accepted: Boolean): Boolean = synchronized(lock) {
        val isCurrent = isCurrentLocked(request)
        if (!isCurrent || !accepted) {
            if (isCurrent) nativeTransformGeneration = null
            return@synchronized false
        }
        nativeTransformGeneration = request.transform.generation
        true
    }

    fun displayState(scene: FullScenePresentation): SceneDisplayState? = synchronized(lock) {
        if (latestScene?.generation != scene.generation) return@synchronized null
        displayStateLocked(scene)
    }

    fun latestDisplayState(): SceneDisplayState? = synchronized(lock) {
        latestScene?.let(::displayStateLocked)
    }

    fun isPromoted(scene: FullScenePresentation): Boolean {
        return displayState(scene)?.nativeBackground == true
    }

    private fun displayStateLocked(scene: FullScenePresentation): SceneDisplayState {
        val transform = latestTransform
        val nativeBackground =
            nativeSceneGeneration == scene.generation &&
                nativeTransformGeneration == transform?.generation
        return SceneDisplayState(scene, transform, nativeBackground)
    }

    private fun isCurrentLocked(request: SceneReplayRequest): Boolean {
        return attachedSurfaceGeneration == request.surfaceGeneration &&
            latestScene?.generation == request.scene.generation &&
            latestTransform?.generation == request.transform?.generation
    }

    private fun isCurrentLocked(request: SceneTransformRequest): Boolean {
        return attachedSurfaceGeneration == request.surfaceGeneration &&
            latestScene?.generation == request.sceneGeneration &&
            latestTransform?.generation == request.transform.generation &&
            nativeSceneGeneration == request.sceneGeneration
    }
}
