#include <jni.h>
#include <android/hardware_buffer.h>
#include <android/hardware_buffer_jni.h>
#include <android/log.h>
#include <android/native_window_jni.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <cctype>
#include <fstream>
#include <initializer_list>
#include <limits>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <vulkan/vulkan.h>
#include <vulkan/vulkan_android.h>
#if defined(__ARM_NEON)
#include <arm_neon.h>
#endif

#include "luvatrix_camera_preview_shaders.h"

#define LVX_LOGI(...) __android_log_print(ANDROID_LOG_INFO, "Luvatrix", __VA_ARGS__)
#define LVX_LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "Luvatrix", __VA_ARGS__)

namespace {

struct Rgba {
    int r = 0;
    int g = 0;
    int b = 0;
    int a = 255;
};

void rgba_to_bgra_in_place(uint8_t* bytes, size_t pixel_count) {
    size_t index = 0;
#if defined(__ARM_NEON)
    for (; index + 16u <= pixel_count; index += 16u) {
        uint8x16x4_t channels = vld4q_u8(bytes + index * 4u);
        std::swap(channels.val[0], channels.val[2]);
        vst4q_u8(bytes + index * 4u, channels);
    }
#endif
    for (; index < pixel_count; ++index) {
        std::swap(bytes[index * 4u], bytes[index * 4u + 2u]);
    }
}

struct CirclePrimitive {
    double cx = 0.0;
    double cy = 0.0;
    double radius = 0.0;
    Rgba fill;
    Rgba stroke;
    double stroke_width = 0.0;
};

struct RectPrimitive {
    double x = 0.0;
    double y = 0.0;
    double width = 0.0;
    double height = 0.0;
    Rgba color;
};

struct TextPrimitive {
    std::string text;
    double x = 0.0;
    double y = 0.0;
    double size = 12.0;
    Rgba color;
};

struct BitmapFont {
    int width = 5;
    int height = 7;
    int advance = 6;
    std::unordered_map<char, std::vector<uint32_t>> glyphs;
    bool loaded = false;
};

struct GlyphBitmap {
    int width = 5;
    int height = 7;
    int advance = 6;
    std::vector<uint32_t> rows;
};

struct ParsedScene {
    Rgba background;
    bool has_rainbow_background = false;
    double background_t = 0.0;
    double background_rotation = 0.0;
    double background_scroll_y = 0.0;
    double content_offset_x = 0.0;
    double content_offset_y = 0.0;
    std::vector<RectPrimitive> rects;
    std::vector<CirclePrimitive> circles;
    std::vector<TextPrimitive> texts;
    std::string presentation_mode;
};

struct VulkanState {
    ANativeWindow* window = nullptr;
    VkInstance instance = VK_NULL_HANDLE;
    VkSurfaceKHR surface = VK_NULL_HANDLE;
    VkPhysicalDevice physical = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    VkQueue queue = VK_NULL_HANDLE;
    uint32_t queue_family = 0;
    VkSwapchainKHR swapchain = VK_NULL_HANDLE;
    VkFormat swapchain_format = VK_FORMAT_B8G8R8A8_UNORM;
    VkExtent2D extent{0, 0};
    std::vector<VkImage> images;
    std::vector<VkImageView> image_views;
    VkRenderPass render_pass = VK_NULL_HANDLE;
    std::vector<VkFramebuffer> framebuffers;
    VkCommandPool command_pool = VK_NULL_HANDLE;
    std::vector<VkCommandBuffer> command_buffers;
    struct PreviewFrameSync {
        VkSemaphore image_available = VK_NULL_HANDLE;
        VkSemaphore render_finished = VK_NULL_HANDLE;
        VkFence in_flight = VK_NULL_HANDLE;
        VkBuffer staging_buffer = VK_NULL_HANDLE;
        VkDeviceMemory staging_memory = VK_NULL_HANDLE;
        VkDeviceSize staging_capacity = 0;
    };
    std::vector<PreviewFrameSync> preview_frames;
    std::vector<VkFence> images_in_flight;
    uint32_t current_frame_slot = 0;
    uint64_t frame_counter = 0;
    VkBuffer staging_buffer = VK_NULL_HANDLE;
    VkDeviceMemory staging_memory = VK_NULL_HANDLE;
    VkDeviceSize staging_capacity = 0;
    VkDescriptorPool preview_descriptor_pool = VK_NULL_HANDLE;
    VkDescriptorSetLayout overlay_descriptor_set_layout = VK_NULL_HANDLE;
    VkPipelineLayout overlay_pipeline_layout = VK_NULL_HANDLE;
    VkPipeline overlay_pipeline = VK_NULL_HANDLE;
    VkShaderModule fullscreen_vertex_shader = VK_NULL_HANDLE;
    VkShaderModule overlay_fragment_shader = VK_NULL_HANDLE;
    VkImage overlay_image = VK_NULL_HANDLE;
    VkDeviceMemory overlay_memory = VK_NULL_HANDLE;
    VkImageView overlay_view = VK_NULL_HANDLE;
    VkSampler overlay_sampler = VK_NULL_HANDLE;
    VkDescriptorSet overlay_descriptor_set = VK_NULL_HANDLE;
    int overlay_width = 0;
    int overlay_height = 0;
    bool overlay_uploaded = false;
    std::string overlay_cache_key;
    VkRenderPass camera_intermediate_render_pass = VK_NULL_HANDLE;
    VkFramebuffer camera_intermediate_framebuffer = VK_NULL_HANDLE;
    VkImage camera_intermediate_image = VK_NULL_HANDLE;
    VkDeviceMemory camera_intermediate_memory = VK_NULL_HANDLE;
    VkImageView camera_intermediate_view = VK_NULL_HANDLE;
    VkSampler camera_intermediate_sampler = VK_NULL_HANDLE;
    VkDescriptorSet camera_intermediate_descriptor_set = VK_NULL_HANDLE;
    VkPipelineLayout camera_intermediate_pipeline_layout = VK_NULL_HANDLE;
    VkPipeline camera_intermediate_pipeline = VK_NULL_HANDLE;
    int camera_intermediate_width = 0;
    int camera_intermediate_height = 0;
    bool camera_intermediate_ready = false;
    int64_t camera_intermediate_timestamp_ns = 0;
    bool preview_base_ready = false;
    int desired_width = 0;
    int desired_height = 0;
    bool initialized = false;
    bool android_hardware_buffer_extensions = false;
};

struct CameraYuvFrame {
    bool preview_enabled = false;
    bool has_frame = false;
    int width = 0;
    int height = 0;
    int y_row_stride = 0;
    int u_row_stride = 0;
    int v_row_stride = 0;
    int y_pixel_stride = 1;
    int u_pixel_stride = 1;
    int v_pixel_stride = 1;
    int64_t timestamp_ns = 0;
    uint64_t frames_received = 0;
    uint64_t dropped_frames = 0;
    int rotation_degrees = 0;
    std::string cover_mode = "cover_center";
    std::vector<uint8_t> y;
    std::vector<uint8_t> u;
    std::vector<uint8_t> v;
};

struct CameraHardwareBufferFrame {
    bool has_frame = false;
    int width = 0;
    int height = 0;
    int64_t timestamp_ns = 0;
    uint64_t frames_received = 0;
    uint64_t dropped_frames = 0;
    int rotation_degrees = 0;
    std::string status = "unavailable";
    std::string last_error;
    AHardwareBuffer* buffer = nullptr;
};

struct GpuPreviewTelemetry {
    std::string status = "fallback";
    int width = 0;
    int height = 0;
    int64_t timestamp_ns = 0;
    uint64_t imports = 0;
    uint64_t draws = 0;
    uint64_t failures = 0;
    int64_t first_import_mono_ns = 0;
    int64_t last_import_mono_ns = 0;
    int64_t first_draw_mono_ns = 0;
    int64_t last_draw_mono_ns = 0;
    double import_fps = 0.0;
    double draw_fps = 0.0;
    double last_draw_ms = 0.0;
    double last_import_ms = 0.0;
    uint64_t queue_waits = 0;
    uint64_t overlay_uploads = 0;
    uint64_t overlay_cache_hits = 0;
    uint64_t imports_on_render_thread = 0;
    uint64_t import_cache_hits = 0;
    uint64_t import_cache_misses = 0;
    uint64_t import_cache_evictions = 0;
    uint32_t import_cache_entries = 0;
    bool last_import_cache_hit = false;
    bool intermediate_enabled = false;
    int intermediate_width = 0;
    int intermediate_height = 0;
    uint64_t intermediate_updates = 0;
    uint64_t intermediate_reuses = 0;
    double last_intermediate_ms = 0.0;
    int64_t intermediate_last_timestamp_ns = 0;
    std::string intermediate_last_error;
    std::string downsample_filter = "natural";
    std::string filter_preset = "natural";
    uint32_t downsample_taps = 5;
    uint32_t filter_taps = 5;
    double downsample_strength = 0.35;
    double luma_smoothing = 0.08;
    double chroma_smoothing = 0.55;
    double edge_preserve = 0.65;
    uint32_t convolution_layers = 0;
    double crop_fit_blend = 0.0;
    std::string color_mode = "auto";
    double red_gain = 1.0;
    double green_gain = 1.0;
    double blue_gain = 1.0;
    double color_brightness = 0.0;
    double color_contrast = 1.0;
    double last_downsample_ms = 0.0;
    double last_filter_ms = 0.0;
    std::string downsample_last_error;
    uint32_t frames_in_flight = 0;
    uint32_t current_frame_slot = 0;
    uint64_t image_fence_waits = 0;
    uint64_t frame_fence_waits = 0;
    uint32_t acquired_image_index = 0;
    std::string sync_mode = "single_fence";
    std::string last_error = "gpu preview renderer is not initialized";
};

struct ImportedCameraPreview {
    bool ready = false;
    int width = 0;
    int height = 0;
    int rotation_degrees = 0;
    int64_t timestamp_ns = 0;
    uint64_t last_used_counter = 0;
    AHardwareBuffer* buffer = nullptr;
    VkImage image = VK_NULL_HANDLE;
    VkDeviceMemory memory = VK_NULL_HANDLE;
    VkImageView image_view = VK_NULL_HANDLE;
    VkSamplerYcbcrConversion conversion = VK_NULL_HANDLE;
    VkSampler sampler = VK_NULL_HANDLE;
    VkDescriptorPool descriptor_pool = VK_NULL_HANDLE;
    VkDescriptorSetLayout descriptor_set_layout = VK_NULL_HANDLE;
    VkPipelineLayout pipeline_layout = VK_NULL_HANDLE;
    VkPipeline pipeline = VK_NULL_HANDLE;
    VkShaderModule fragment_shader = VK_NULL_HANDLE;
    VkDescriptorSet descriptor_set = VK_NULL_HANDLE;
};

struct CameraPushConstants {
    float scale_x = 1.0f;
    float scale_y = 1.0f;
    float offset_x = 0.0f;
    float offset_y = 0.0f;
    float rotation_degrees = 0.0f;
    float luma_smoothing = 0.0f;
    float chroma_smoothing = 0.0f;
    float edge_preserve = 0.0f;
    float detail_boost = 0.0f;
    float filter_mode = 0.0f;
    float color_contrast = 1.0f;
    float reserved1 = 0.0f;
    float red_gain = 1.0f;
    float green_gain = 1.0f;
    float blue_gain = 1.0f;
    float color_brightness = 0.0f;
};

std::mutex g_mutex;
VulkanState g_vk;
ParsedScene g_retained_scene;
bool g_retained_scene_available = false;
int g_retained_scene_revision = 0;
int g_retained_scene_width = 1;
int g_retained_scene_height = 1;
std::string g_downsample_filter = "natural";
uint32_t g_downsample_taps = 5;
float g_downsample_strength = 0.15f;
float g_luma_smoothing = 0.08f;
float g_downsample_mode = 0.0f;
float g_chroma_smoothing = 0.55f;
float g_edge_preserve = 0.65f;
uint32_t g_convolution_layers = 0;
float g_crop_fit_blend = 0.0f;
std::string g_color_mode = "auto";
float g_red_gain = 1.0f;
float g_green_gain = 1.0f;
float g_blue_gain = 1.0f;
float g_color_brightness = 0.0f;
float g_color_contrast = 1.0f;
BitmapFont g_bitmap_font;
CameraYuvFrame g_camera_primary;
CameraYuvFrame g_camera_secondary;
CameraHardwareBufferFrame g_hardware_primary;
CameraHardwareBufferFrame g_hardware_secondary;
GpuPreviewTelemetry g_gpu_preview;
std::vector<ImportedCameraPreview> g_imported_camera_preview_cache;
int g_active_imported_camera_preview = -1;
uint64_t g_imported_camera_preview_use_counter = 0;
const char* g_preview_renderer = "cpu_yuv_bilinear";
bool g_preview_gpu_ready = false;
constexpr size_t kMaxImportedCameraPreviewCacheEntries = 12;
constexpr uint32_t kPreviewFramesInFlight = 2;

int64_t monotonic_now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()
    ).count();
}

double fps_from_window(uint64_t count, int64_t first_ns, int64_t last_ns) {
    if (count < 2 || first_ns <= 0 || last_ns <= first_ns) return 0.0;
    return static_cast<double>(count - 1) * 1000000000.0 / static_cast<double>(last_ns - first_ns);
}

bool wait_fence_for_preview(VulkanState& vk, VkFence fence, uint64_t* split_counter, bool reset_after_wait) {
    if (vk.device == VK_NULL_HANDLE || fence == VK_NULL_HANDLE) return true;
    VkResult status = vkGetFenceStatus(vk.device, fence);
    if (status == VK_SUCCESS) {
        if (reset_after_wait) {
            return vkResetFences(vk.device, 1, &fence) == VK_SUCCESS;
        }
        return true;
    }
    if (status != VK_NOT_READY) return false;
    VkResult wait = vkWaitForFences(vk.device, 1, &fence, VK_TRUE, UINT64_MAX);
    g_gpu_preview.queue_waits += 1;
    if (split_counter != nullptr) {
        *split_counter += 1;
    }
    if (wait != VK_SUCCESS) return false;
    if (reset_after_wait) {
        return vkResetFences(vk.device, 1, &fence) == VK_SUCCESS;
    }
    return true;
}

bool wait_all_preview_frame_fences(VulkanState& vk) {
    if (vk.device == VK_NULL_HANDLE) return true;
    for (auto& frame : vk.preview_frames) {
        if (!wait_fence_for_preview(vk, frame.in_flight, nullptr, false)) {
            return false;
        }
    }
    return true;
}

PFN_vkCreateSamplerYcbcrConversionKHR load_create_sampler_ycbcr_conversion(VulkanState& vk) {
    auto fn = reinterpret_cast<PFN_vkCreateSamplerYcbcrConversionKHR>(
        vkGetDeviceProcAddr(vk.device, "vkCreateSamplerYcbcrConversionKHR")
    );
    if (fn != nullptr) return fn;
    return reinterpret_cast<PFN_vkCreateSamplerYcbcrConversionKHR>(
        vkGetDeviceProcAddr(vk.device, "vkCreateSamplerYcbcrConversion")
    );
}

PFN_vkDestroySamplerYcbcrConversionKHR load_destroy_sampler_ycbcr_conversion(VulkanState& vk) {
    auto fn = reinterpret_cast<PFN_vkDestroySamplerYcbcrConversionKHR>(
        vkGetDeviceProcAddr(vk.device, "vkDestroySamplerYcbcrConversionKHR")
    );
    if (fn != nullptr) return fn;
    return reinterpret_cast<PFN_vkDestroySamplerYcbcrConversionKHR>(
        vkGetDeviceProcAddr(vk.device, "vkDestroySamplerYcbcrConversion")
    );
}

int count_nodes(const std::string& scene_json) {
    int count = 0;
    const std::string needle = "\"type\"";
    std::string::size_type pos = 0;
    while ((pos = scene_json.find(needle, pos)) != std::string::npos) {
        ++count;
        pos += needle.size();
    }
    return count;
}

int clamp255(int v) {
    return std::max(0, std::min(255, v));
}

std::optional<double> number_after(const std::string& text, std::string::size_type pos) {
    if (pos == std::string::npos) return std::nullopt;
    while (pos < text.size() && text[pos] != '-' && text[pos] != '+' && text[pos] != '.' && (text[pos] < '0' || text[pos] > '9')) {
        ++pos;
    }
    if (pos >= text.size()) return std::nullopt;
    char* end = nullptr;
    double value = std::strtod(text.c_str() + pos, &end);
    if (end == text.c_str() + pos) return std::nullopt;
    return value;
}

Rgba parse_color_array(const std::string& json, const std::string& key, Rgba fallback) {
    auto key_pos = json.find("\"" + key + "\"");
    if (key_pos == std::string::npos) return fallback;
    auto open = json.find('[', key_pos);
    auto close = json.find(']', open);
    if (open == std::string::npos || close == std::string::npos) return fallback;
    std::array<int, 4> values{fallback.r, fallback.g, fallback.b, fallback.a};
    auto pos = open + 1;
    for (int i = 0; i < 4 && pos < close; ++i) {
        auto value = number_after(json, pos);
        if (!value.has_value()) break;
        values[i] = clamp255(static_cast<int>(*value));
        auto comma = json.find(',', pos);
        if (comma == std::string::npos || comma > close) break;
        pos = comma + 1;
    }
    return Rgba{values[0], values[1], values[2], values[3]};
}

Rgba parse_scene_background(const std::string& json) {
    Rgba fallback = parse_color_array(json, "color", Rgba{0, 0, 0, 255});
    auto shader = json.find("\"shader\":\"full_suite_background\"");
    if (shader == std::string::npos) return fallback;
    auto uniforms = json.find("\"uniforms\"", shader);
    auto open = json.find('[', uniforms);
    if (open == std::string::npos) return fallback;
    auto t = number_after(json, open + 1).value_or(0.0);
    auto comma1 = json.find(',', open + 1);
    auto rotation = number_after(json, comma1 == std::string::npos ? open + 1 : comma1 + 1).value_or(0.0);
    auto comma2 = comma1 == std::string::npos ? std::string::npos : json.find(',', comma1 + 1);
    auto scroll_y = number_after(json, comma2 == std::string::npos ? open + 1 : comma2 + 1).value_or(0.0);
    int ti = static_cast<int>(t);
    int base_r = (ti * 3 + 35) % 255;
    int base_g = (ti * 2 + 70) % 255;
    int base_b = (ti * 4 + 20) % 255;
    int rotate_boost = static_cast<int>(std::max(-30.0, std::min(30.0, rotation * 2.0)));
    int scroll_boost = static_cast<int>(std::max(-40.0, std::min(40.0, scroll_y * 0.5)));
    return Rgba{clamp255(base_r + rotate_boost), clamp255(base_g + scroll_boost), clamp255(base_b), 255};
}

void parse_background_uniforms(const std::string& json, ParsedScene& scene) {
    auto uniforms = json.find("\"uniforms\"");
    auto open = json.find('[', uniforms);
    if (uniforms == std::string::npos || open == std::string::npos) return;
    scene.has_rainbow_background = true;
    scene.background_t = number_after(json, open + 1).value_or(0.0);
    auto comma1 = json.find(',', open + 1);
    scene.background_rotation = number_after(json, comma1 == std::string::npos ? open + 1 : comma1 + 1).value_or(0.0);
    auto comma2 = comma1 == std::string::npos ? std::string::npos : json.find(',', comma1 + 1);
    scene.background_scroll_y = number_after(json, comma2 == std::string::npos ? open + 1 : comma2 + 1).value_or(0.0);
}

std::string::size_type value_pos_after_key(const std::string& json, const std::string& key) {
    auto key_pos = json.find("\"" + key + "\"");
    if (key_pos == std::string::npos) return std::string::npos;
    auto colon = json.find(':', key_pos);
    return colon == std::string::npos ? std::string::npos : colon + 1;
}

double parse_number_key(const std::string& json, const std::string& key, double fallback = 0.0) {
    auto pos = value_pos_after_key(json, key);
    return number_after(json, pos).value_or(fallback);
}

std::string parse_string_key(const std::string& json, const std::string& key) {
    auto pos = value_pos_after_key(json, key);
    if (pos == std::string::npos) return "";
    auto open = json.find('"', pos);
    if (open == std::string::npos) return "";
    std::string out;
    bool escape = false;
    for (auto i = open + 1; i < json.size(); ++i) {
        char ch = json[i];
        if (escape) {
            switch (ch) {
                case 'n': out.push_back('\n'); break;
                case 't': out.push_back('\t'); break;
                case 'r': out.push_back('\r'); break;
                default: out.push_back(ch); break;
            }
            escape = false;
        } else if (ch == '\\') {
            escape = true;
        } else if (ch == '"') {
            break;
        } else {
            out.push_back(ch);
        }
    }
    return out;
}

std::string parse_type(const std::string& node) {
    return parse_string_key(node, "type");
}

std::vector<std::string> parse_node_objects(const std::string& json) {
    std::vector<std::string> out;
    int depth = 0;
    bool in_string = false;
    bool escape = false;
    std::string::size_type start = std::string::npos;
    for (std::string::size_type i = 0; i < json.size(); ++i) {
        char ch = json[i];
        if (in_string) {
            if (escape) {
                escape = false;
            } else if (ch == '\\') {
                escape = true;
            } else if (ch == '"') {
                in_string = false;
            }
            continue;
        }
        if (ch == '"') {
            in_string = true;
        } else if (ch == '{') {
            if (depth == 0) start = i;
            ++depth;
        } else if (ch == '}') {
            --depth;
            if (depth == 0 && start != std::string::npos) {
                out.push_back(json.substr(start, i - start + 1));
                start = std::string::npos;
            }
        }
    }
    return out;
}

ParsedScene parse_scene(const std::string& json) {
    ParsedScene scene;
    scene.background = parse_scene_background(json);
    const auto nodes = parse_node_objects(json);

    // Look for meta node to extract scene-wide rendering state.
    for (const auto& node : nodes) {
        std::string type = parse_type(node);
        if (type == "meta") {
            std::string presentation_mode_from_json = parse_string_key(node, "presentation_mode");
            if (!presentation_mode_from_json.empty()) scene.presentation_mode = presentation_mode_from_json;
            scene.content_offset_x = parse_number_key(node, "content_offset_x", scene.content_offset_x);
            scene.content_offset_y = parse_number_key(node, "content_offset_y", scene.content_offset_y);
        }
    }

    for (const auto& node : nodes) {
        std::string type = parse_type(node);
        if (type == "clear") {
            scene.background = parse_color_array(node, "color", scene.background);
        } else if (type == "shader_rect" && parse_string_key(node, "shader") == "full_suite_background") {
            scene.background = parse_scene_background(node);
            parse_background_uniforms(node, scene);
        } else if (type == "rect") {
            scene.rects.push_back(RectPrimitive{
                parse_number_key(node, "x"),
                parse_number_key(node, "y"),
                parse_number_key(node, "w"),
                parse_number_key(node, "h"),
                parse_color_array(node, "color", Rgba{255, 255, 255, 255}),
            });
        } else if (type == "circle") {
            scene.circles.push_back(CirclePrimitive{
                parse_number_key(node, "cx"),
                parse_number_key(node, "cy"),
                parse_number_key(node, "r"),
                parse_color_array(node, "fill", Rgba{255, 255, 255, 255}),
                parse_color_array(node, "stroke", Rgba{255, 255, 255, 255}),
                parse_number_key(node, "stroke_width"),
            });
        } else if (type == "text") {
            scene.texts.push_back(TextPrimitive{
                parse_string_key(node, "text"),
                parse_number_key(node, "x"),
                parse_number_key(node, "y"),
                parse_number_key(node, "size", 12.0),
                parse_color_array(node, "color", Rgba{255, 255, 255, 255}),
            });
        }
    }
    return scene;
}

class BinarySceneReader {
public:
    BinarySceneReader(const uint8_t* data, size_t size) : cursor_(data), end_(data + size) {}

    bool read_u8(uint8_t& value) {
        if (cursor_ >= end_) return false;
        value = *cursor_++;
        return true;
    }

    bool read_u16(uint16_t& value) {
        if (static_cast<size_t>(end_ - cursor_) < 2) return false;
        value = static_cast<uint16_t>(cursor_[0]) | (static_cast<uint16_t>(cursor_[1]) << 8U);
        cursor_ += 2;
        return true;
    }

    bool read_double(double& value) {
        if (static_cast<size_t>(end_ - cursor_) < sizeof(value)) return false;
        std::memcpy(&value, cursor_, sizeof(value));
        cursor_ += sizeof(value);
        return std::isfinite(value);
    }

    bool read_color(Rgba& value) {
        uint8_t r = 0, g = 0, b = 0, a = 0;
        if (!read_u8(r) || !read_u8(g) || !read_u8(b) || !read_u8(a)) return false;
        value = Rgba{static_cast<int>(r), static_cast<int>(g), static_cast<int>(b), static_cast<int>(a)};
        return true;
    }

    bool read_string(uint16_t size, std::string& value) {
        if (static_cast<size_t>(end_ - cursor_) < size) return false;
        value.assign(reinterpret_cast<const char*>(cursor_), size);
        cursor_ += size;
        return true;
    }

private:
    const uint8_t* cursor_;
    const uint8_t* end_;
};

bool parse_scene_binary(const uint8_t* data, size_t size, ParsedScene& scene) {
    constexpr char kMagic[] = "LVXS";
    if (data == nullptr || size < 23 || std::memcmp(data, kMagic, 4) != 0) return false;
    BinarySceneReader reader(data + 4, size - 4);
    uint8_t version = 0;
    uint16_t node_count = 0;
    ParsedScene parsed;
    if (!reader.read_u8(version) || version != 1 || !reader.read_u16(node_count) ||
        !reader.read_double(parsed.content_offset_x) || !reader.read_double(parsed.content_offset_y)) {
        return false;
    }
    for (uint16_t index = 0; index < node_count; ++index) {
        uint8_t type = 0;
        if (!reader.read_u8(type)) return false;
        if (type == 1) {
            continue;
        }
        if (type == 2) {
            if (!reader.read_color(parsed.background)) return false;
        } else if (type == 3) {
            double x = 0.0, y = 0.0, width = 0.0, height = 0.0;
            uint8_t shader = 0;
            Rgba color;
            uint16_t uniform_count = 0;
            if (!reader.read_double(x) || !reader.read_double(y) || !reader.read_double(width) || !reader.read_double(height) ||
                !reader.read_u8(shader) || !reader.read_color(color) || !reader.read_u16(uniform_count)) return false;
            std::vector<double> uniforms(uniform_count);
            for (double& uniform : uniforms) if (!reader.read_double(uniform)) return false;
            if (shader == 1) {
                parsed.background = color;
                parsed.has_rainbow_background = true;
                if (!uniforms.empty()) parsed.background_t = uniforms[0];
                if (uniforms.size() > 1) parsed.background_rotation = uniforms[1];
                if (uniforms.size() > 2) parsed.background_scroll_y = uniforms[2];
            }
        } else if (type == 4) {
            RectPrimitive rect;
            if (!reader.read_double(rect.x) || !reader.read_double(rect.y) || !reader.read_double(rect.width) ||
                !reader.read_double(rect.height) || !reader.read_color(rect.color)) return false;
            parsed.rects.push_back(rect);
        } else if (type == 5) {
            CirclePrimitive circle;
            if (!reader.read_double(circle.cx) || !reader.read_double(circle.cy) || !reader.read_double(circle.radius) ||
                !reader.read_double(circle.stroke_width) || !reader.read_color(circle.fill) || !reader.read_color(circle.stroke)) return false;
            parsed.circles.push_back(circle);
        } else if (type == 6) {
            TextPrimitive text;
            uint16_t text_size = 0;
            if (!reader.read_double(text.x) || !reader.read_double(text.y) || !reader.read_double(text.size) ||
                !reader.read_color(text.color) || !reader.read_u16(text_size) || !reader.read_string(text_size, text.text)) return false;
            parsed.texts.push_back(std::move(text));
        } else {
            return false;
        }
    }
    scene = std::move(parsed);
    return true;
}

void destroy_imported_camera_preview_entry(VulkanState& vk, ImportedCameraPreview& entry) {
    if (vk.device != VK_NULL_HANDLE) {
        if (entry.pipeline != VK_NULL_HANDLE) {
            vkDestroyPipeline(vk.device, entry.pipeline, nullptr);
        }
        if (entry.pipeline_layout != VK_NULL_HANDLE) {
            vkDestroyPipelineLayout(vk.device, entry.pipeline_layout, nullptr);
        }
        if (entry.descriptor_set_layout != VK_NULL_HANDLE) {
            vkDestroyDescriptorSetLayout(vk.device, entry.descriptor_set_layout, nullptr);
        }
        if (entry.fragment_shader != VK_NULL_HANDLE) {
            vkDestroyShaderModule(vk.device, entry.fragment_shader, nullptr);
        }
        if (entry.descriptor_pool != VK_NULL_HANDLE) {
            vkDestroyDescriptorPool(vk.device, entry.descriptor_pool, nullptr);
        }
        if (entry.image_view != VK_NULL_HANDLE) {
            vkDestroyImageView(vk.device, entry.image_view, nullptr);
        }
        if (entry.sampler != VK_NULL_HANDLE) {
            vkDestroySampler(vk.device, entry.sampler, nullptr);
        }
    }
    if (entry.conversion != VK_NULL_HANDLE && vk.device != VK_NULL_HANDLE) {
        auto destroy_conversion = load_destroy_sampler_ycbcr_conversion(vk);
        if (destroy_conversion != nullptr) {
            destroy_conversion(vk.device, entry.conversion, nullptr);
        }
    }
    if (vk.device != VK_NULL_HANDLE) {
        if (entry.image != VK_NULL_HANDLE) {
            vkDestroyImage(vk.device, entry.image, nullptr);
        }
        if (entry.memory != VK_NULL_HANDLE) {
            vkFreeMemory(vk.device, entry.memory, nullptr);
        }
    }
    if (entry.buffer != nullptr) {
        AHardwareBuffer_release(entry.buffer);
    }
    entry = ImportedCameraPreview{};
}

void destroy_imported_camera_preview(VulkanState& vk) {
    for (auto& entry : g_imported_camera_preview_cache) {
        destroy_imported_camera_preview_entry(vk, entry);
    }
    g_imported_camera_preview_cache.clear();
    g_active_imported_camera_preview = -1;
    g_gpu_preview.import_cache_entries = 0;
}

void destroy_camera_intermediate_resources(VulkanState& vk) {
    if (vk.device == VK_NULL_HANDLE) return;
    if (vk.camera_intermediate_pipeline != VK_NULL_HANDLE) {
        vkDestroyPipeline(vk.device, vk.camera_intermediate_pipeline, nullptr);
        vk.camera_intermediate_pipeline = VK_NULL_HANDLE;
    }
    if (vk.camera_intermediate_pipeline_layout != VK_NULL_HANDLE) {
        vkDestroyPipelineLayout(vk.device, vk.camera_intermediate_pipeline_layout, nullptr);
        vk.camera_intermediate_pipeline_layout = VK_NULL_HANDLE;
    }
    if (vk.camera_intermediate_framebuffer != VK_NULL_HANDLE) {
        vkDestroyFramebuffer(vk.device, vk.camera_intermediate_framebuffer, nullptr);
        vk.camera_intermediate_framebuffer = VK_NULL_HANDLE;
    }
    if (vk.camera_intermediate_view != VK_NULL_HANDLE) {
        vkDestroyImageView(vk.device, vk.camera_intermediate_view, nullptr);
        vk.camera_intermediate_view = VK_NULL_HANDLE;
    }
    if (vk.camera_intermediate_sampler != VK_NULL_HANDLE) {
        vkDestroySampler(vk.device, vk.camera_intermediate_sampler, nullptr);
        vk.camera_intermediate_sampler = VK_NULL_HANDLE;
    }
    if (vk.camera_intermediate_image != VK_NULL_HANDLE) {
        vkDestroyImage(vk.device, vk.camera_intermediate_image, nullptr);
        vk.camera_intermediate_image = VK_NULL_HANDLE;
    }
    if (vk.camera_intermediate_memory != VK_NULL_HANDLE) {
        vkFreeMemory(vk.device, vk.camera_intermediate_memory, nullptr);
        vk.camera_intermediate_memory = VK_NULL_HANDLE;
    }
    if (vk.camera_intermediate_render_pass != VK_NULL_HANDLE) {
        vkDestroyRenderPass(vk.device, vk.camera_intermediate_render_pass, nullptr);
        vk.camera_intermediate_render_pass = VK_NULL_HANDLE;
    }
    vk.camera_intermediate_descriptor_set = VK_NULL_HANDLE;
    vk.camera_intermediate_width = 0;
    vk.camera_intermediate_height = 0;
    vk.camera_intermediate_ready = false;
    vk.camera_intermediate_timestamp_ns = 0;
    g_gpu_preview.intermediate_enabled = false;
    g_gpu_preview.intermediate_width = 0;
    g_gpu_preview.intermediate_height = 0;
    g_gpu_preview.intermediate_last_timestamp_ns = 0;
}

void destroy_preview_base_resources(VulkanState& vk) {
    if (vk.device == VK_NULL_HANDLE) return;
    destroy_imported_camera_preview(vk);
    destroy_camera_intermediate_resources(vk);
    if (vk.overlay_pipeline != VK_NULL_HANDLE) {
        vkDestroyPipeline(vk.device, vk.overlay_pipeline, nullptr);
        vk.overlay_pipeline = VK_NULL_HANDLE;
    }
    if (vk.overlay_pipeline_layout != VK_NULL_HANDLE) {
        vkDestroyPipelineLayout(vk.device, vk.overlay_pipeline_layout, nullptr);
        vk.overlay_pipeline_layout = VK_NULL_HANDLE;
    }
    if (vk.overlay_descriptor_set_layout != VK_NULL_HANDLE) {
        vkDestroyDescriptorSetLayout(vk.device, vk.overlay_descriptor_set_layout, nullptr);
        vk.overlay_descriptor_set_layout = VK_NULL_HANDLE;
    }
    if (vk.fullscreen_vertex_shader != VK_NULL_HANDLE) {
        vkDestroyShaderModule(vk.device, vk.fullscreen_vertex_shader, nullptr);
        vk.fullscreen_vertex_shader = VK_NULL_HANDLE;
    }
    if (vk.overlay_fragment_shader != VK_NULL_HANDLE) {
        vkDestroyShaderModule(vk.device, vk.overlay_fragment_shader, nullptr);
        vk.overlay_fragment_shader = VK_NULL_HANDLE;
    }
    if (vk.overlay_view != VK_NULL_HANDLE) {
        vkDestroyImageView(vk.device, vk.overlay_view, nullptr);
        vk.overlay_view = VK_NULL_HANDLE;
    }
    if (vk.overlay_sampler != VK_NULL_HANDLE) {
        vkDestroySampler(vk.device, vk.overlay_sampler, nullptr);
        vk.overlay_sampler = VK_NULL_HANDLE;
    }
    if (vk.overlay_image != VK_NULL_HANDLE) {
        vkDestroyImage(vk.device, vk.overlay_image, nullptr);
        vk.overlay_image = VK_NULL_HANDLE;
    }
    if (vk.overlay_memory != VK_NULL_HANDLE) {
        vkFreeMemory(vk.device, vk.overlay_memory, nullptr);
        vk.overlay_memory = VK_NULL_HANDLE;
    }
    if (vk.preview_descriptor_pool != VK_NULL_HANDLE) {
        vkDestroyDescriptorPool(vk.device, vk.preview_descriptor_pool, nullptr);
        vk.preview_descriptor_pool = VK_NULL_HANDLE;
    }
    vk.overlay_descriptor_set = VK_NULL_HANDLE;
    vk.overlay_width = 0;
    vk.overlay_height = 0;
    vk.overlay_uploaded = false;
    vk.overlay_cache_key.clear();
    vk.preview_base_ready = false;
}

void destroy_swapchain(VulkanState& vk) {
    if (vk.device != VK_NULL_HANDLE) {
        vkDeviceWaitIdle(vk.device);
        destroy_preview_base_resources(vk);
        for (auto framebuffer : vk.framebuffers) vkDestroyFramebuffer(vk.device, framebuffer, nullptr);
        vk.framebuffers.clear();
        if (!vk.command_buffers.empty() && vk.command_pool != VK_NULL_HANDLE) {
            vkFreeCommandBuffers(vk.device, vk.command_pool, static_cast<uint32_t>(vk.command_buffers.size()), vk.command_buffers.data());
            vk.command_buffers.clear();
        }
        if (vk.command_pool != VK_NULL_HANDLE) {
            vkDestroyCommandPool(vk.device, vk.command_pool, nullptr);
            vk.command_pool = VK_NULL_HANDLE;
        }
        if (vk.render_pass != VK_NULL_HANDLE) {
            vkDestroyRenderPass(vk.device, vk.render_pass, nullptr);
            vk.render_pass = VK_NULL_HANDLE;
        }
        for (auto view : vk.image_views) vkDestroyImageView(vk.device, view, nullptr);
        vk.image_views.clear();
        if (vk.swapchain != VK_NULL_HANDLE) {
            vkDestroySwapchainKHR(vk.device, vk.swapchain, nullptr);
            vk.swapchain = VK_NULL_HANDLE;
        }
    }
    vk.images.clear();
    vk.images_in_flight.clear();
    vk.extent = VkExtent2D{0, 0};
}

void destroy_vulkan(VulkanState& vk) {
    destroy_swapchain(vk);
    if (vk.device != VK_NULL_HANDLE) {
        for (auto& frame : vk.preview_frames) {
            if (frame.image_available != VK_NULL_HANDLE) vkDestroySemaphore(vk.device, frame.image_available, nullptr);
            if (frame.render_finished != VK_NULL_HANDLE) vkDestroySemaphore(vk.device, frame.render_finished, nullptr);
            if (frame.in_flight != VK_NULL_HANDLE) vkDestroyFence(vk.device, frame.in_flight, nullptr);
            if (frame.staging_buffer != VK_NULL_HANDLE) vkDestroyBuffer(vk.device, frame.staging_buffer, nullptr);
            if (frame.staging_memory != VK_NULL_HANDLE) vkFreeMemory(vk.device, frame.staging_memory, nullptr);
        }
        vk.preview_frames.clear();
        if (vk.staging_buffer != VK_NULL_HANDLE) vkDestroyBuffer(vk.device, vk.staging_buffer, nullptr);
        if (vk.staging_memory != VK_NULL_HANDLE) vkFreeMemory(vk.device, vk.staging_memory, nullptr);
        vkDestroyDevice(vk.device, nullptr);
    }
    if (vk.surface != VK_NULL_HANDLE && vk.instance != VK_NULL_HANDLE) vkDestroySurfaceKHR(vk.instance, vk.surface, nullptr);
    if (vk.instance != VK_NULL_HANDLE) vkDestroyInstance(vk.instance, nullptr);
    if (vk.window != nullptr) ANativeWindow_release(vk.window);
    vk = VulkanState{};
}

bool create_instance(VulkanState& vk) {
    uint32_t extension_count = 0;
    VkResult enumerate = vkEnumerateInstanceExtensionProperties(nullptr, &extension_count, nullptr);
    if (enumerate != VK_SUCCESS) {
        LVX_LOGE("vkEnumerateInstanceExtensionProperties failed before create_instance: %d", enumerate);
        return false;
    }
    std::vector<VkExtensionProperties> available(extension_count);
    vkEnumerateInstanceExtensionProperties(nullptr, &extension_count, available.data());
    bool has_surface = false;
    bool has_android_surface = false;
    for (const auto& extension : available) {
        if (std::strcmp(extension.extensionName, "VK_KHR_surface") == 0) has_surface = true;
        if (std::strcmp(extension.extensionName, "VK_KHR_android_surface") == 0) has_android_surface = true;
    }
    if (!has_surface || !has_android_surface) {
        LVX_LOGE(
            "required Vulkan surface extensions missing: VK_KHR_surface=%d VK_KHR_android_surface=%d extension_count=%u",
            has_surface ? 1 : 0,
            has_android_surface ? 1 : 0,
            extension_count
        );
        return false;
    }
    const char* extensions[] = {"VK_KHR_surface", "VK_KHR_android_surface"};
    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.pApplicationName = "Luvatrix";
    app.applicationVersion = VK_MAKE_VERSION(0, 1, 0);
    app.pEngineName = "Luvatrix";
    app.engineVersion = VK_MAKE_VERSION(0, 1, 0);
    app.apiVersion = VK_API_VERSION_1_0;
    VkInstanceCreateInfo ci{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    ci.pApplicationInfo = &app;
    ci.enabledExtensionCount = 2;
    ci.ppEnabledExtensionNames = extensions;
    VkResult result = vkCreateInstance(&ci, nullptr, &vk.instance);
    if (result != VK_SUCCESS) {
        LVX_LOGE("vkCreateInstance failed: %d", result);
        return false;
    }
    return true;
}

bool create_surface(VulkanState& vk) {
    if (vk.window == nullptr) {
        LVX_LOGE("vkCreateAndroidSurfaceKHR skipped: null ANativeWindow");
        return false;
    }
    if (vk.desired_width > 0 && vk.desired_height > 0) {
        int result = ANativeWindow_setBuffersGeometry(vk.window, vk.desired_width, vk.desired_height, 0);
        if (result != 0) {
            LVX_LOGE(
                "ANativeWindow_setBuffersGeometry failed: %d requested=%dx%d",
                result,
                vk.desired_width,
                vk.desired_height
            );
        }
    }
    int window_width = ANativeWindow_getWidth(vk.window);
    int window_height = ANativeWindow_getHeight(vk.window);
    LVX_LOGI(
        "creating Android Vulkan surface window=%p size=%dx%d requested=%dx%d",
        vk.window,
        window_width,
        window_height,
        vk.desired_width,
        vk.desired_height
    );
    VkAndroidSurfaceCreateInfoKHR ci{VK_STRUCTURE_TYPE_ANDROID_SURFACE_CREATE_INFO_KHR};
    ci.window = vk.window;
    VkResult result = vkCreateAndroidSurfaceKHR(vk.instance, &ci, nullptr, &vk.surface);
    if (result != VK_SUCCESS) {
        LVX_LOGE("vkCreateAndroidSurfaceKHR failed: %d", result);
        return false;
    }
    return true;
}

bool pick_device(VulkanState& vk) {
    uint32_t count = 0;
    vkEnumeratePhysicalDevices(vk.instance, &count, nullptr);
    if (count == 0) return false;
    std::vector<VkPhysicalDevice> devices(count);
    vkEnumeratePhysicalDevices(vk.instance, &count, devices.data());
    for (auto device : devices) {
        uint32_t q_count = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(device, &q_count, nullptr);
        std::vector<VkQueueFamilyProperties> queues(q_count);
        vkGetPhysicalDeviceQueueFamilyProperties(device, &q_count, queues.data());
        for (uint32_t i = 0; i < q_count; ++i) {
            VkBool32 present = VK_FALSE;
            vkGetPhysicalDeviceSurfaceSupportKHR(device, i, vk.surface, &present);
            if ((queues[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) && present) {
                vk.physical = device;
                vk.queue_family = i;
                return true;
            }
        }
    }
    return false;
}

bool create_device(VulkanState& vk) {
    float priority = 1.0f;
    VkDeviceQueueCreateInfo qci{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    qci.queueFamilyIndex = vk.queue_family;
    qci.queueCount = 1;
    qci.pQueuePriorities = &priority;
    uint32_t extension_count = 0;
    vkEnumerateDeviceExtensionProperties(vk.physical, nullptr, &extension_count, nullptr);
    std::vector<VkExtensionProperties> available(extension_count);
    if (extension_count > 0) {
        vkEnumerateDeviceExtensionProperties(vk.physical, nullptr, &extension_count, available.data());
    }
    auto has_extension = [&](const char* name) {
        for (const auto& extension : available) {
            if (std::strcmp(extension.extensionName, name) == 0) return true;
        }
        return false;
    };
    std::vector<const char*> extensions = {"VK_KHR_swapchain"};
    bool has_ahb = has_extension("VK_ANDROID_external_memory_android_hardware_buffer");
    bool has_external_memory = has_extension("VK_KHR_external_memory");
    bool has_ycbcr = has_extension("VK_KHR_sampler_ycbcr_conversion");
    bool has_foreign_queue = has_extension("VK_EXT_queue_family_foreign");
    if (has_ahb && has_external_memory && has_ycbcr && has_foreign_queue) {
        extensions.push_back("VK_ANDROID_external_memory_android_hardware_buffer");
        extensions.push_back("VK_KHR_external_memory");
        extensions.push_back("VK_KHR_sampler_ycbcr_conversion");
        extensions.push_back("VK_EXT_queue_family_foreign");
        vk.android_hardware_buffer_extensions = true;
    } else {
        vk.android_hardware_buffer_extensions = false;
        LVX_LOGI(
            "Vulkan AHardwareBuffer preview extensions unavailable AHB=%d external=%d ycbcr=%d foreign=%d",
            has_ahb ? 1 : 0,
            has_external_memory ? 1 : 0,
            has_ycbcr ? 1 : 0,
            has_foreign_queue ? 1 : 0
        );
    }
    VkDeviceCreateInfo dci{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    dci.queueCreateInfoCount = 1;
    dci.pQueueCreateInfos = &qci;
    dci.enabledExtensionCount = static_cast<uint32_t>(extensions.size());
    dci.ppEnabledExtensionNames = extensions.data();
    VkResult create_result = vkCreateDevice(vk.physical, &dci, nullptr, &vk.device);
    if (create_result != VK_SUCCESS && vk.android_hardware_buffer_extensions) {
        LVX_LOGI("vkCreateDevice failed with AHardwareBuffer preview extensions (%d); retrying swapchain-only", create_result);
        vk.android_hardware_buffer_extensions = false;
        extensions = {"VK_KHR_swapchain"};
        dci.enabledExtensionCount = static_cast<uint32_t>(extensions.size());
        dci.ppEnabledExtensionNames = extensions.data();
        create_result = vkCreateDevice(vk.physical, &dci, nullptr, &vk.device);
    }
    if (create_result != VK_SUCCESS) return false;
    vkGetDeviceQueue(vk.device, vk.queue_family, 0, &vk.queue);
    VkSemaphoreCreateInfo sci{VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
    VkFenceCreateInfo fci{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    fci.flags = VK_FENCE_CREATE_SIGNALED_BIT;
    vk.preview_frames.resize(kPreviewFramesInFlight);
    for (auto& frame : vk.preview_frames) {
        if (vkCreateSemaphore(vk.device, &sci, nullptr, &frame.image_available) != VK_SUCCESS) return false;
        if (vkCreateSemaphore(vk.device, &sci, nullptr, &frame.render_finished) != VK_SUCCESS) return false;
        if (vkCreateFence(vk.device, &fci, nullptr, &frame.in_flight) != VK_SUCCESS) return false;
    }
    g_gpu_preview.frames_in_flight = static_cast<uint32_t>(vk.preview_frames.size());
    g_gpu_preview.sync_mode = "frames_in_flight";
    return true;
}

VkSurfaceFormatKHR choose_format(const std::vector<VkSurfaceFormatKHR>& formats) {
    for (const auto& format : formats) {
        if (format.format == VK_FORMAT_B8G8R8A8_UNORM && format.colorSpace == VK_COLOR_SPACE_SRGB_NONLINEAR_KHR) return format;
    }
    return formats[0];
}

bool create_swapchain(VulkanState& vk) {
    VkSurfaceCapabilitiesKHR caps{};
    vkGetPhysicalDeviceSurfaceCapabilitiesKHR(vk.physical, vk.surface, &caps);
    uint32_t format_count = 0;
    vkGetPhysicalDeviceSurfaceFormatsKHR(vk.physical, vk.surface, &format_count, nullptr);
    if (format_count == 0) return false;
    std::vector<VkSurfaceFormatKHR> formats(format_count);
    vkGetPhysicalDeviceSurfaceFormatsKHR(vk.physical, vk.surface, &format_count, formats.data());
    auto format = choose_format(formats);
    vk.swapchain_format = format.format;
    if (caps.currentExtent.width != UINT32_MAX) {
        vk.extent = caps.currentExtent;
    } else {
        vk.extent = VkExtent2D{
            static_cast<uint32_t>(std::max(1, ANativeWindow_getWidth(vk.window))),
            static_cast<uint32_t>(std::max(1, ANativeWindow_getHeight(vk.window))),
        };
    }
    uint32_t image_count = caps.minImageCount + 1;
    if (caps.maxImageCount > 0 && image_count > caps.maxImageCount) image_count = caps.maxImageCount;
    VkSwapchainCreateInfoKHR sci{VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR};
    sci.surface = vk.surface;
    sci.minImageCount = image_count;
    sci.imageFormat = vk.swapchain_format;
    sci.imageColorSpace = format.colorSpace;
    sci.imageExtent = vk.extent;
    sci.imageArrayLayers = 1;
    sci.imageUsage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    sci.imageSharingMode = VK_SHARING_MODE_EXCLUSIVE;
    sci.preTransform = caps.currentTransform;
    sci.compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
    sci.presentMode = VK_PRESENT_MODE_FIFO_KHR;
    sci.clipped = VK_TRUE;
    if (vkCreateSwapchainKHR(vk.device, &sci, nullptr, &vk.swapchain) != VK_SUCCESS) return false;
    uint32_t actual_count = 0;
    vkGetSwapchainImagesKHR(vk.device, vk.swapchain, &actual_count, nullptr);
    vk.images.resize(actual_count);
    vkGetSwapchainImagesKHR(vk.device, vk.swapchain, &actual_count, vk.images.data());
    return true;
}

bool create_render_resources(VulkanState& vk) {
    for (auto image : vk.images) {
        VkImageViewCreateInfo iv{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
        iv.image = image;
        iv.viewType = VK_IMAGE_VIEW_TYPE_2D;
        iv.format = vk.swapchain_format;
        iv.components = {VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY};
        iv.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        iv.subresourceRange.baseMipLevel = 0;
        iv.subresourceRange.levelCount = 1;
        iv.subresourceRange.baseArrayLayer = 0;
        iv.subresourceRange.layerCount = 1;
        VkImageView view = VK_NULL_HANDLE;
        if (vkCreateImageView(vk.device, &iv, nullptr, &view) != VK_SUCCESS) return false;
        vk.image_views.push_back(view);
    }
    VkAttachmentDescription color{};
    color.format = vk.swapchain_format;
    color.samples = VK_SAMPLE_COUNT_1_BIT;
    color.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    color.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    color.stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    color.stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    color.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    color.finalLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
    VkAttachmentReference ref{};
    ref.attachment = 0;
    ref.layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    VkSubpassDescription subpass{};
    subpass.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    subpass.colorAttachmentCount = 1;
    subpass.pColorAttachments = &ref;
    VkRenderPassCreateInfo rp{VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO};
    rp.attachmentCount = 1;
    rp.pAttachments = &color;
    rp.subpassCount = 1;
    rp.pSubpasses = &subpass;
    if (vkCreateRenderPass(vk.device, &rp, nullptr, &vk.render_pass) != VK_SUCCESS) return false;
    for (auto view : vk.image_views) {
        VkFramebufferCreateInfo fb{VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO};
        fb.renderPass = vk.render_pass;
        fb.attachmentCount = 1;
        fb.pAttachments = &view;
        fb.width = vk.extent.width;
        fb.height = vk.extent.height;
        fb.layers = 1;
        VkFramebuffer framebuffer = VK_NULL_HANDLE;
        if (vkCreateFramebuffer(vk.device, &fb, nullptr, &framebuffer) != VK_SUCCESS) return false;
        vk.framebuffers.push_back(framebuffer);
    }
    VkCommandPoolCreateInfo cp{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    cp.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    cp.queueFamilyIndex = vk.queue_family;
    if (vkCreateCommandPool(vk.device, &cp, nullptr, &vk.command_pool) != VK_SUCCESS) return false;
    vk.command_buffers.resize(vk.images.size());
    VkCommandBufferAllocateInfo alloc{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    alloc.commandPool = vk.command_pool;
    alloc.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    alloc.commandBufferCount = static_cast<uint32_t>(vk.command_buffers.size());
    if (vkAllocateCommandBuffers(vk.device, &alloc, vk.command_buffers.data()) != VK_SUCCESS) return false;
    vk.images_in_flight.assign(vk.images.size(), VK_NULL_HANDLE);
    vk.current_frame_slot = 0;
    vk.frame_counter = 0;
    g_gpu_preview.current_frame_slot = 0;
    g_gpu_preview.acquired_image_index = 0;
    return true;
}

bool ensure_vulkan(VulkanState& vk) {
    if (vk.initialized) return true;
    if (vk.window == nullptr) return false;
    if (!create_instance(vk)) {
        LVX_LOGE("failed to initialize Android Vulkan scene background renderer: create_instance");
        destroy_vulkan(vk);
        return false;
    }
    if (!create_surface(vk)) {
        LVX_LOGE("failed to initialize Android Vulkan scene background renderer: create_surface");
        destroy_vulkan(vk);
        return false;
    }
    if (!pick_device(vk)) {
        LVX_LOGE("failed to initialize Android Vulkan scene background renderer: pick_device");
        destroy_vulkan(vk);
        return false;
    }
    if (!create_device(vk)) {
        LVX_LOGE("failed to initialize Android Vulkan scene background renderer: create_device");
        destroy_vulkan(vk);
        return false;
    }
    if (!create_swapchain(vk)) {
        LVX_LOGE("failed to initialize Android Vulkan scene background renderer: create_swapchain");
        destroy_vulkan(vk);
        return false;
    }
    if (!create_render_resources(vk)) {
        LVX_LOGE("failed to initialize Android Vulkan scene background renderer: create_render_resources");
        destroy_vulkan(vk);
        return false;
    }
    vk.initialized = true;
    LVX_LOGI("luvatrix Android Vulkan scene background ready extent=%ux%u", vk.extent.width, vk.extent.height);
    return true;
}

uint32_t pack_bgra(Rgba color) {
    return static_cast<uint32_t>(clamp255(color.b))
        | (static_cast<uint32_t>(clamp255(color.g)) << 8)
        | (static_cast<uint32_t>(clamp255(color.r)) << 16)
        | (static_cast<uint32_t>(clamp255(color.a)) << 24);
}

void convert_bgra_pixels_for_swapchain(std::vector<uint32_t>& pixels, VkFormat format) {
    if (format != VK_FORMAT_R8G8B8A8_UNORM && format != VK_FORMAT_R8G8B8A8_SRGB) {
        return;
    }
    for (uint32_t& pixel : pixels) {
        uint32_t b = pixel & 0x000000ffu;
        uint32_t g = pixel & 0x0000ff00u;
        uint32_t r = pixel & 0x00ff0000u;
        uint32_t a = pixel & 0xff000000u;
        pixel = (r >> 16) | g | (b << 16) | a;
    }
}

uint8_t plane_value(const std::vector<uint8_t>& plane, int x, int y, int row_stride, int pixel_stride) {
    if (row_stride <= 0 || pixel_stride <= 0 || x < 0 || y < 0) return 128;
    size_t idx = static_cast<size_t>(y) * static_cast<size_t>(row_stride) +
                 static_cast<size_t>(x) * static_cast<size_t>(pixel_stride);
    if (idx >= plane.size()) return 128;
    return plane[idx];
}

double plane_value_bilinear(
    const std::vector<uint8_t>& plane,
    double x,
    double y,
    int max_x,
    int max_y,
    int row_stride,
    int pixel_stride
) {
    if (row_stride <= 0 || pixel_stride <= 0 || max_x <= 0 || max_y <= 0) return 128.0;
    double sx = std::max(0.0, std::min(static_cast<double>(max_x - 1), x));
    double sy = std::max(0.0, std::min(static_cast<double>(max_y - 1), y));
    int x0 = static_cast<int>(std::floor(sx));
    int y0 = static_cast<int>(std::floor(sy));
    int x1 = std::min(max_x - 1, x0 + 1);
    int y1 = std::min(max_y - 1, y0 + 1);
    double tx = sx - static_cast<double>(x0);
    double ty = sy - static_cast<double>(y0);
    double p00 = static_cast<double>(plane_value(plane, x0, y0, row_stride, pixel_stride));
    double p10 = static_cast<double>(plane_value(plane, x1, y0, row_stride, pixel_stride));
    double p01 = static_cast<double>(plane_value(plane, x0, y1, row_stride, pixel_stride));
    double p11 = static_cast<double>(plane_value(plane, x1, y1, row_stride, pixel_stride));
    double top = p00 + (p10 - p00) * tx;
    double bottom = p01 + (p11 - p01) * tx;
    return top + (bottom - top) * ty;
}

uint32_t yuv_to_bgra(uint8_t y_raw, uint8_t u_raw, uint8_t v_raw) {
    int y = static_cast<int>(y_raw);
    int u = static_cast<int>(u_raw) - 128;
    int v = static_cast<int>(v_raw) - 128;
    int r = static_cast<int>(std::round(static_cast<double>(y) + 1.402 * static_cast<double>(v)));
    int g = static_cast<int>(std::round(static_cast<double>(y) - 0.344136 * static_cast<double>(u) - 0.714136 * static_cast<double>(v)));
    int b = static_cast<int>(std::round(static_cast<double>(y) + 1.772 * static_cast<double>(u)));
    return pack_bgra(Rgba{r, g, b, 255});
}

uint32_t yuv_to_bgra(double y_raw, double u_raw, double v_raw) {
    int y = static_cast<int>(std::round(y_raw));
    int u = static_cast<int>(std::round(u_raw)) - 128;
    int v = static_cast<int>(std::round(v_raw)) - 128;
    int r = static_cast<int>(std::round(static_cast<double>(y) + 1.402 * static_cast<double>(v)));
    int g = static_cast<int>(std::round(static_cast<double>(y) - 0.344136 * static_cast<double>(u) - 0.714136 * static_cast<double>(v)));
    int b = static_cast<int>(std::round(static_cast<double>(y) + 1.772 * static_cast<double>(u)));
    return pack_bgra(Rgba{r, g, b, 255});
}

CameraYuvFrame& camera_slot(const std::string& slot) {
    return slot == "secondary" ? g_camera_secondary : g_camera_primary;
}

const CameraYuvFrame& camera_slot_const(const std::string& slot) {
    return slot == "secondary" ? g_camera_secondary : g_camera_primary;
}

CameraHardwareBufferFrame& hardware_slot(const std::string& slot) {
    return slot == "secondary" ? g_hardware_secondary : g_hardware_primary;
}

const CameraHardwareBufferFrame& hardware_slot_const(const std::string& slot) {
    return slot == "secondary" ? g_hardware_secondary : g_hardware_primary;
}

void release_hardware_buffer(CameraHardwareBufferFrame& frame) {
    if (frame.buffer != nullptr) {
        AHardwareBuffer_release(frame.buffer);
        frame.buffer = nullptr;
    }
}

std::vector<uint32_t> camera_preview_pixels(const CameraYuvFrame& camera, int out_width, int out_height) {
    std::vector<uint32_t> pixels(static_cast<size_t>(out_width) * static_cast<size_t>(out_height), pack_bgra(Rgba{0, 0, 0, 255}));
    if (!camera.preview_enabled || !camera.has_frame || camera.width <= 0 || camera.height <= 0) {
        return pixels;
    }
    int rotation = ((camera.rotation_degrees % 360) + 360) % 360;
    bool rotated = rotation == 90 || rotation == 270;
    int oriented_width = rotated ? camera.height : camera.width;
    int oriented_height = rotated ? camera.width : camera.height;
    double scale = 1.0;
    double visible_w = 0.0;
    double visible_h = 0.0;
    if (camera.cover_mode == "pixel_crop") {
        double pixel_w = std::min(static_cast<double>(out_width), static_cast<double>(oriented_width));
        double pixel_h = std::min(static_cast<double>(out_height), static_cast<double>(oriented_height));
        double cover_scale = std::max(
            static_cast<double>(out_width) / static_cast<double>(std::max(1, oriented_width)),
            static_cast<double>(out_height) / static_cast<double>(std::max(1, oriented_height))
        );
        double cover_w = static_cast<double>(out_width) / std::max(0.0001, cover_scale);
        double cover_h = static_cast<double>(out_height) / std::max(0.0001, cover_scale);
        double blend = std::max(0.0, std::min(1.0, static_cast<double>(g_crop_fit_blend)));
        visible_w = pixel_w + (cover_w - pixel_w) * blend;
        visible_h = pixel_h + (cover_h - pixel_h) * blend;
    } else {
        scale = std::max(
            static_cast<double>(out_width) / static_cast<double>(std::max(1, oriented_width)),
            static_cast<double>(out_height) / static_cast<double>(std::max(1, oriented_height))
        );
        visible_w = static_cast<double>(out_width) / scale;
        visible_h = static_cast<double>(out_height) / scale;
    }
    double src_x0 = (static_cast<double>(oriented_width) - visible_w) * 0.5;
    double src_y0 = (static_cast<double>(oriented_height) - visible_h) * 0.5;
    int chroma_width = std::max(1, (camera.width + 1) / 2);
    int chroma_height = std::max(1, (camera.height + 1) / 2);
    for (int oy = 0; oy < out_height; ++oy) {
        double oriented_y = std::max(0.0, std::min(static_cast<double>(oriented_height - 1), src_y0 + static_cast<double>(oy) / scale));
        for (int ox = 0; ox < out_width; ++ox) {
            double oriented_x = std::max(0.0, std::min(static_cast<double>(oriented_width - 1), src_x0 + static_cast<double>(ox) / scale));
            double sx = oriented_x;
            double sy = oriented_y;
            if (rotation == 90) {
                sx = oriented_y;
                sy = static_cast<double>(camera.height - 1) - oriented_x;
            } else if (rotation == 180) {
                sx = static_cast<double>(camera.width - 1) - oriented_x;
                sy = static_cast<double>(camera.height - 1) - oriented_y;
            } else if (rotation == 270) {
                sx = static_cast<double>(camera.width - 1) - oriented_y;
                sy = oriented_x;
            }
            sx = std::max(0.0, std::min(static_cast<double>(camera.width - 1), sx));
            sy = std::max(0.0, std::min(static_cast<double>(camera.height - 1), sy));
            double y = plane_value_bilinear(camera.y, sx, sy, camera.width, camera.height, camera.y_row_stride, camera.y_pixel_stride);
            double u = plane_value_bilinear(camera.u, sx * 0.5, sy * 0.5, chroma_width, chroma_height, camera.u_row_stride, camera.u_pixel_stride);
            double v = plane_value_bilinear(camera.v, sx * 0.5, sy * 0.5, chroma_width, chroma_height, camera.v_row_stride, camera.v_pixel_stride);
            pixels[static_cast<size_t>(oy) * static_cast<size_t>(out_width) + static_cast<size_t>(ox)] = yuv_to_bgra(y, u, v);
        }
    }
    return pixels;
}

std::vector<uint32_t> render_camera_preview_pixels(const CameraYuvFrame& camera, int out_width, int out_height) {
    return camera_preview_pixels(camera, out_width, out_height);
}

void draw_secondary_inset(std::vector<uint32_t>& pixels, int width, int height) {
    const CameraYuvFrame& secondary = g_camera_secondary;
    if (!secondary.preview_enabled || !secondary.has_frame || secondary.width <= 0 || secondary.height <= 0) return;
    int inset_w = std::max(96, width / 4);
    int inset_h = std::max(72, static_cast<int>(std::round(static_cast<double>(inset_w) * secondary.height / std::max(1, secondary.width))));
    inset_h = std::min(inset_h, std::max(1, height / 3));
    int margin = std::max(12, std::min(width, height) / 32);
    int x0 = std::max(0, width - inset_w - margin);
    int y0 = margin;
    auto inset = render_camera_preview_pixels(secondary, inset_w, inset_h);
    for (int y = 0; y < inset_h && y0 + y < height; ++y) {
        for (int x = 0; x < inset_w && x0 + x < width; ++x) {
            pixels[static_cast<size_t>(y0 + y) * static_cast<size_t>(width) + static_cast<size_t>(x0 + x)] =
                inset[static_cast<size_t>(y) * static_cast<size_t>(inset_w) + static_cast<size_t>(x)];
        }
    }
    uint32_t border = pack_bgra(Rgba{214, 240, 244, 220});
    for (int x = x0 - 2; x < x0 + inset_w + 2; ++x) {
        if (x >= 0 && x < width) {
            for (int yy : {y0 - 2, y0 - 1, y0 + inset_h, y0 + inset_h + 1}) {
                if (yy >= 0 && yy < height) pixels[static_cast<size_t>(yy) * static_cast<size_t>(width) + static_cast<size_t>(x)] = border;
            }
        }
    }
    for (int y = y0 - 2; y < y0 + inset_h + 2; ++y) {
        if (y >= 0 && y < height) {
            for (int xx : {x0 - 2, x0 - 1, x0 + inset_w, x0 + inset_w + 1}) {
                if (xx >= 0 && xx < width) pixels[static_cast<size_t>(y) * static_cast<size_t>(width) + static_cast<size_t>(xx)] = border;
            }
        }
    }
}

Rgba hsv_to_rgba(double h, double s, double v) {
    h = h - std::floor(h);
    double c = v * s;
    double x = c * (1.0 - std::fabs(std::fmod(h * 6.0, 2.0) - 1.0));
    double m = v - c;
    double r = 0.0;
    double g = 0.0;
    double b = 0.0;
    if (h < 1.0 / 6.0) {
        r = c; g = x; b = 0.0;
    } else if (h < 2.0 / 6.0) {
        r = x; g = c; b = 0.0;
    } else if (h < 3.0 / 6.0) {
        r = 0.0; g = c; b = x;
    } else if (h < 4.0 / 6.0) {
        r = 0.0; g = x; b = c;
    } else if (h < 5.0 / 6.0) {
        r = x; g = 0.0; b = c;
    } else {
        r = c; g = 0.0; b = x;
    }
    return Rgba{
        clamp255(static_cast<int>((r + m) * 255.0)),
        clamp255(static_cast<int>((g + m) * 255.0)),
        clamp255(static_cast<int>((b + m) * 255.0)),
        255,
    };
}

void fill_rainbow_background(std::vector<uint32_t>& pixels, int width, int height, const ParsedScene& scene) {
    constexpr int kPaletteSize = 1024;
    std::array<uint32_t, kPaletteSize> palette{};
    double t = scene.background_t * 0.0025 + scene.background_rotation * 0.01 + scene.background_scroll_y * 0.002;
    for (int i = 0; i < kPaletteSize; ++i) {
        double hue = (static_cast<double>(i) / static_cast<double>(kPaletteSize)) + t;
        double value = 0.84 + 0.10 * (static_cast<double>((i * 37) & 255) / 255.0);
        palette[static_cast<size_t>(i)] = pack_bgra(hsv_to_rgba(hue, 0.82, value));
    }
    int phase = static_cast<int>(std::floor(t * static_cast<double>(kPaletteSize))) & (kPaletteSize - 1);
    int x_step = std::max(1, kPaletteSize / std::max(1, width));
    int y_step = std::max(1, kPaletteSize / std::max(1, height));
    for (int y = 0; y < height; ++y) {
        int row = (phase + y * y_step * 2) & (kPaletteSize - 1);
        for (int x = 0; x < width; ++x) {
            pixels[static_cast<size_t>(y) * static_cast<size_t>(width) + static_cast<size_t>(x)] = palette[(row + x * x_step * 3) & (kPaletteSize - 1)];
        }
    }
}

void blend_pixel(std::vector<uint32_t>& pixels, int width, int height, int x, int y, Rgba src) {
    if (x < 0 || y < 0 || x >= width || y >= height || src.a <= 0) return;
    uint32_t& dst = pixels[static_cast<size_t>(y) * static_cast<size_t>(width) + static_cast<size_t>(x)];
    if (src.a >= 255) {
        dst = pack_bgra(src);
        return;
    }
    int db = static_cast<int>(dst & 0xff);
    int dg = static_cast<int>((dst >> 8) & 0xff);
    int dr = static_cast<int>((dst >> 16) & 0xff);
    int da = static_cast<int>((dst >> 24) & 0xff);
    int inv = 255 - clamp255(src.a);
    int out_a = clamp255(src.a + (da * inv + 127) / 255);
    int out_r = (src.r * src.a + dr * inv + 127) / 255;
    int out_g = (src.g * src.a + dg * inv + 127) / 255;
    int out_b = (src.b * src.a + db * inv + 127) / 255;
    dst = pack_bgra(Rgba{out_r, out_g, out_b, out_a});
}

void draw_rect_pixels(
    std::vector<uint32_t>& pixels,
    int width,
    int height,
    double scale_x,
    double scale_y,
    const RectPrimitive& rect
) {
    int x0 = static_cast<int>(std::floor(rect.x * scale_x));
    int y0 = static_cast<int>(std::floor(rect.y * scale_y));
    int x1 = static_cast<int>(std::ceil((rect.x + rect.width) * scale_x));
    int y1 = static_cast<int>(std::ceil((rect.y + rect.height) * scale_y));
    x0 = std::max(0, std::min(width, x0));
    x1 = std::max(0, std::min(width, x1));
    y0 = std::max(0, std::min(height, y0));
    y1 = std::max(0, std::min(height, y1));
    for (int y = y0; y < y1; ++y) {
        for (int x = x0; x < x1; ++x) blend_pixel(pixels, width, height, x, y, rect.color);
    }
}

void draw_circle_pixels(
    std::vector<uint32_t>& pixels,
    int width,
    int height,
    double scale_x,
    double scale_y,
    const CirclePrimitive& circle
) {
    double scale = std::min(scale_x, scale_y);
    double cx = circle.cx * scale_x;
    double cy = circle.cy * scale_y;
    double radius = std::max(0.0, circle.radius * scale);
    double stroke = std::max(0.0, circle.stroke_width * scale);
    if (radius <= 0.0) return;
    int x0 = std::max(0, static_cast<int>(std::floor(cx - radius - stroke - 1.0)));
    int x1 = std::min(width - 1, static_cast<int>(std::ceil(cx + radius + stroke + 1.0)));
    int y0 = std::max(0, static_cast<int>(std::floor(cy - radius - stroke - 1.0)));
    int y1 = std::min(height - 1, static_cast<int>(std::ceil(cy + radius + stroke + 1.0)));
    double outer = radius + stroke * 0.5;
    double inner_stroke = std::max(0.0, radius - stroke * 0.5);
    double fill_limit = stroke > 0.0 ? inner_stroke : radius;
    for (int y = y0; y <= y1; ++y) {
        for (int x = x0; x <= x1; ++x) {
            double dx = (static_cast<double>(x) + 0.5) - cx;
            double dy = (static_cast<double>(y) + 0.5) - cy;
            double dist = std::sqrt(dx * dx + dy * dy);
            if (dist <= fill_limit) {
                blend_pixel(pixels, width, height, x, y, circle.fill);
            } else if (stroke > 0.0 && dist <= outer) {
                blend_pixel(pixels, width, height, x, y, circle.stroke);
            }
        }
    }
}

std::string trim_copy(const std::string& value) {
    auto start = value.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    auto end = value.find_last_not_of(" \t\r\n");
    return value.substr(start, end - start + 1);
}

std::optional<int> parse_int_value(const std::string& value) {
    char* end = nullptr;
    long parsed = std::strtol(value.c_str(), &end, 10);
    if (end == value.c_str()) return std::nullopt;
    return static_cast<int>(parsed);
}

std::optional<char> parse_glyph_key(const std::string& raw_key) {
    std::string key = trim_copy(raw_key);
    if (key == "space") return ' ';
    if (key == "colon") return ':';
    if (key == "period") return '.';
    if (key == "comma") return ',';
    if (key == "dash") return '-';
    if (key == "underscore") return '_';
    if (key == "equals") return '=';
    if (key == "pipe") return '|';
    if (key == "slash") return '/';
    if (key.rfind("U+", 0) == 0 || key.rfind("u+", 0) == 0) {
        char* end = nullptr;
        long code = std::strtol(key.c_str() + 2, &end, 16);
        if (end == key.c_str() + 2 || code < 0 || code > 127) return std::nullopt;
        return static_cast<char>(code);
    }
    if (key.size() == 1) return key[0];
    return std::nullopt;
}

bool parse_bitmap_font_table(const std::string& source, BitmapFont& out) {
    BitmapFont parsed;
    size_t pos = 0;
    while (pos <= source.size()) {
        size_t next = source.find('\n', pos);
        std::string line = trim_copy(source.substr(pos, next == std::string::npos ? std::string::npos : next - pos));
        pos = next == std::string::npos ? source.size() + 1 : next + 1;
        if (line.empty() || line[0] == '#') continue;
        auto eq = line.find('=');
        if (eq == std::string::npos) continue;
        std::string key = trim_copy(line.substr(0, eq));
        std::string value = trim_copy(line.substr(eq + 1));
        if (key == "width") {
            parsed.width = std::max(1, std::min(32, parse_int_value(value).value_or(parsed.width)));
            continue;
        }
        if (key == "height") {
            parsed.height = std::max(1, std::min(64, parse_int_value(value).value_or(parsed.height)));
            continue;
        }
        if (key == "advance") {
            parsed.advance = std::max(1, std::min(64, parse_int_value(value).value_or(parsed.advance)));
            continue;
        }
        auto glyph_key = parse_glyph_key(key);
        if (!glyph_key.has_value()) continue;
        std::vector<uint32_t> rows;
        size_t row_pos = 0;
        while (row_pos <= value.size()) {
            size_t comma = value.find(',', row_pos);
            std::string token = trim_copy(value.substr(row_pos, comma == std::string::npos ? std::string::npos : comma - row_pos));
            row_pos = comma == std::string::npos ? value.size() + 1 : comma + 1;
            if (token.empty()) continue;
            char* end = nullptr;
            unsigned long row = std::strtoul(token.c_str(), &end, 16);
            if (end == token.c_str()) {
                rows.clear();
                break;
            }
            rows.push_back(static_cast<uint32_t>(row));
        }
        if (static_cast<int>(rows.size()) == parsed.height) {
            parsed.glyphs[*glyph_key] = rows;
        }
    }
    if (parsed.glyphs.empty()) return false;
    parsed.loaded = true;
    out = std::move(parsed);
    return true;
}

std::array<uint8_t, 7> builtin_glyph_rows(char raw) {
    char ch = raw >= 'a' && raw <= 'z' ? static_cast<char>(raw - 'a' + 'A') : raw;
    switch (ch) {
        case 'A': return {0x0e,0x11,0x11,0x1f,0x11,0x11,0x11};
        case 'B': return {0x1e,0x11,0x11,0x1e,0x11,0x11,0x1e};
        case 'C': return {0x0e,0x11,0x10,0x10,0x10,0x11,0x0e};
        case 'D': return {0x1e,0x11,0x11,0x11,0x11,0x11,0x1e};
        case 'E': return {0x1f,0x10,0x10,0x1e,0x10,0x10,0x1f};
        case 'F': return {0x1f,0x10,0x10,0x1e,0x10,0x10,0x10};
        case 'G': return {0x0e,0x11,0x10,0x17,0x11,0x11,0x0f};
        case 'H': return {0x11,0x11,0x11,0x1f,0x11,0x11,0x11};
        case 'I': return {0x0e,0x04,0x04,0x04,0x04,0x04,0x0e};
        case 'J': return {0x07,0x02,0x02,0x02,0x12,0x12,0x0c};
        case 'K': return {0x11,0x12,0x14,0x18,0x14,0x12,0x11};
        case 'L': return {0x10,0x10,0x10,0x10,0x10,0x10,0x1f};
        case 'M': return {0x11,0x1b,0x15,0x15,0x11,0x11,0x11};
        case 'N': return {0x11,0x19,0x15,0x13,0x11,0x11,0x11};
        case 'O': return {0x0e,0x11,0x11,0x11,0x11,0x11,0x0e};
        case 'P': return {0x1e,0x11,0x11,0x1e,0x10,0x10,0x10};
        case 'Q': return {0x0e,0x11,0x11,0x11,0x15,0x12,0x0d};
        case 'R': return {0x1e,0x11,0x11,0x1e,0x14,0x12,0x11};
        case 'S': return {0x0f,0x10,0x10,0x0e,0x01,0x01,0x1e};
        case 'T': return {0x1f,0x04,0x04,0x04,0x04,0x04,0x04};
        case 'U': return {0x11,0x11,0x11,0x11,0x11,0x11,0x0e};
        case 'V': return {0x11,0x11,0x11,0x11,0x11,0x0a,0x04};
        case 'W': return {0x11,0x11,0x11,0x15,0x15,0x15,0x0a};
        case 'X': return {0x11,0x11,0x0a,0x04,0x0a,0x11,0x11};
        case 'Y': return {0x11,0x11,0x0a,0x04,0x04,0x04,0x04};
        case 'Z': return {0x1f,0x01,0x02,0x04,0x08,0x10,0x1f};
        case '0': return {0x0e,0x11,0x13,0x15,0x19,0x11,0x0e};
        case '1': return {0x04,0x0c,0x04,0x04,0x04,0x04,0x0e};
        case '2': return {0x0e,0x11,0x01,0x02,0x04,0x08,0x1f};
        case '3': return {0x1e,0x01,0x01,0x0e,0x01,0x01,0x1e};
        case '4': return {0x02,0x06,0x0a,0x12,0x1f,0x02,0x02};
        case '5': return {0x1f,0x10,0x10,0x1e,0x01,0x01,0x1e};
        case '6': return {0x0e,0x10,0x10,0x1e,0x11,0x11,0x0e};
        case '7': return {0x1f,0x01,0x02,0x04,0x08,0x08,0x08};
        case '8': return {0x0e,0x11,0x11,0x0e,0x11,0x11,0x0e};
        case '9': return {0x0e,0x11,0x11,0x0f,0x01,0x01,0x0e};
        case ':': return {0x00,0x04,0x04,0x00,0x04,0x04,0x00};
        case '.': return {0x00,0x00,0x00,0x00,0x00,0x0c,0x0c};
        case ',': return {0x00,0x00,0x00,0x00,0x04,0x04,0x08};
        case '-': return {0x00,0x00,0x00,0x1f,0x00,0x00,0x00};
        case '_': return {0x00,0x00,0x00,0x00,0x00,0x00,0x1f};
        case '=': return {0x00,0x00,0x1f,0x00,0x1f,0x00,0x00};
        case '|': return {0x04,0x04,0x04,0x04,0x04,0x04,0x04};
        case '/': return {0x01,0x01,0x02,0x04,0x08,0x10,0x10};
        case ' ': return {0x00,0x00,0x00,0x00,0x00,0x00,0x00};
        default: return {0x1f,0x11,0x05,0x02,0x04,0x00,0x04};
    }
}

GlyphBitmap glyph_bitmap(char raw) {
    char ch = raw >= 'a' && raw <= 'z' ? static_cast<char>(raw - 'a' + 'A') : raw;
    if (g_bitmap_font.loaded) {
        auto found = g_bitmap_font.glyphs.find(ch);
        if (found == g_bitmap_font.glyphs.end() && raw >= 'a' && raw <= 'z') {
            found = g_bitmap_font.glyphs.find(raw);
        }
        if (found != g_bitmap_font.glyphs.end()) {
            return GlyphBitmap{g_bitmap_font.width, g_bitmap_font.height, g_bitmap_font.advance, found->second};
        }
    }
    auto builtin = builtin_glyph_rows(raw);
    return GlyphBitmap{5, 7, 6, std::vector<uint32_t>(builtin.begin(), builtin.end())};
}

void draw_text_pixels(
    std::vector<uint32_t>& pixels,
    int width,
    int height,
    double scale_x,
    double scale_y,
    const TextPrimitive& text
) {
    if (text.text.empty() || text.color.a <= 0) return;
    double scale = std::max(1.0, std::min(scale_x, scale_y));
    int x_cursor = static_cast<int>(std::round(text.x * scale_x));
    int y_top = static_cast<int>(std::round(text.y * scale_y));
    int line_start = x_cursor;
    for (char ch : text.text) {
        GlyphBitmap glyph = glyph_bitmap(ch);
        int px = std::max(1, static_cast<int>(std::round(text.size * scale / static_cast<double>(std::max(1, glyph.height)))));
        if (ch == '\n') {
            x_cursor = line_start;
            y_top += px * (glyph.height + 2);
            continue;
        }
        for (int row = 0; row < glyph.height && row < static_cast<int>(glyph.rows.size()); ++row) {
            for (int col = 0; col < glyph.width; ++col) {
                if ((glyph.rows[row] & (1u << (glyph.width - 1 - col))) == 0) continue;
                int x0 = x_cursor + col * px;
                int y0 = y_top + row * px;
                for (int yy = 0; yy < px; ++yy) {
                    for (int xx = 0; xx < px; ++xx) {
                        blend_pixel(pixels, width, height, x0 + xx, y0 + yy, text.color);
                    }
                }
            }
        }
        x_cursor += px * glyph.advance;
    }
}

std::vector<uint32_t> rasterize_scene_pixels_impl(
    const ParsedScene& scene,
    int width,
    int height,
    int logical_width,
    int logical_height,
    bool include_cpu_camera_background,
    bool transparent_background
) {
    bool use_camera_background = include_cpu_camera_background && g_camera_primary.preview_enabled && g_camera_primary.has_frame;
    std::vector<uint32_t> pixels;
    if (transparent_background) {
        pixels.assign(static_cast<size_t>(width) * static_cast<size_t>(height), 0u);
    } else if (use_camera_background) {
        pixels = render_camera_preview_pixels(g_camera_primary, width, height);
    } else {
        pixels.assign(static_cast<size_t>(width) * static_cast<size_t>(height), pack_bgra(scene.background));
    }
    if (!transparent_background && !use_camera_background && scene.has_rainbow_background) fill_rainbow_background(pixels, width, height, scene);
    draw_secondary_inset(pixels, width, height);
    double scale_x = static_cast<double>(width) / static_cast<double>(std::max(1, logical_width));
    double scale_y = static_cast<double>(height) / static_cast<double>(std::max(1, logical_height));
    for (const auto& rect : scene.rects) {
        RectPrimitive shifted = rect;
        shifted.x -= scene.content_offset_x;
        shifted.y -= scene.content_offset_y;
        draw_rect_pixels(pixels, width, height, scale_x, scale_y, shifted);
    }
    for (const auto& circle : scene.circles) {
        CirclePrimitive shifted = circle;
        shifted.cx -= scene.content_offset_x;
        shifted.cy -= scene.content_offset_y;
        draw_circle_pixels(pixels, width, height, scale_x, scale_y, shifted);
    }
    for (const auto& text : scene.texts) {
        TextPrimitive shifted = text;
        shifted.x -= scene.content_offset_x;
        shifted.y -= scene.content_offset_y;
        draw_text_pixels(pixels, width, height, scale_x, scale_y, shifted);
    }
    return pixels;
}

std::vector<uint32_t> rasterize_scene_pixels(const ParsedScene& scene, int width, int height, int logical_width, int logical_height) {
    return rasterize_scene_pixels_impl(scene, width, height, logical_width, logical_height, true, false);
}

std::vector<uint32_t> rasterize_overlay_pixels(const ParsedScene& scene, int width, int height, int logical_width, int logical_height) {
    return rasterize_scene_pixels_impl(scene, width, height, logical_width, logical_height, false, true);
}

uint32_t find_memory_type(VulkanState& vk, uint32_t bits, VkMemoryPropertyFlags flags) {
    VkPhysicalDeviceMemoryProperties props{};
    vkGetPhysicalDeviceMemoryProperties(vk.physical, &props);
    for (uint32_t i = 0; i < props.memoryTypeCount; ++i) {
        if ((bits & (1u << i)) && (props.memoryTypes[i].propertyFlags & flags) == flags) return i;
    }
    return std::numeric_limits<uint32_t>::max();
}

bool ensure_preview_base_resources(VulkanState& vk);
void image_barrier(VkCommandBuffer cmd, VkImage image, VkImageLayout old_layout, VkImageLayout new_layout);
bool create_texture_descriptor_set_layout(VulkanState& vk, const VkSampler* immutable_sampler, VkDescriptorSetLayout& layout);
void update_texture_descriptor(VulkanState& vk, VkDescriptorSet set, VkImageView view, VkSampler sampler);
VkShaderModule create_shader_module(VulkanState& vk, const uint32_t* words, size_t word_count);
bool create_fullscreen_pipeline(
    VulkanState& vk,
    VkDescriptorSetLayout descriptor_layout,
    VkShaderModule fragment_shader,
    bool alpha_blend,
    bool camera_push_constants,
    VkPipelineLayout& pipeline_layout,
    VkPipeline& pipeline,
    VkRenderPass render_pass = VK_NULL_HANDLE
);

void set_gpu_preview_error(const std::string& error, int width, int height, int64_t timestamp_ns) {
    g_gpu_preview.status = "fallback";
    g_gpu_preview.width = width;
    g_gpu_preview.height = height;
    g_gpu_preview.timestamp_ns = timestamp_ns;
    g_gpu_preview.failures += 1;
    g_gpu_preview.last_error = error;
    g_gpu_preview.intermediate_last_error = error;
    g_preview_gpu_ready = false;
}

void cleanup_imported_hardware_preview(
    VulkanState& vk,
    VkImageView image_view,
    VkSampler sampler,
    VkSamplerYcbcrConversion conversion,
    VkDeviceMemory memory,
    VkImage image
) {
    if (image_view != VK_NULL_HANDLE) vkDestroyImageView(vk.device, image_view, nullptr);
    if (sampler != VK_NULL_HANDLE) vkDestroySampler(vk.device, sampler, nullptr);
    if (conversion != VK_NULL_HANDLE) {
        auto destroy_conversion = load_destroy_sampler_ycbcr_conversion(vk);
        if (destroy_conversion != nullptr) {
            destroy_conversion(vk.device, conversion, nullptr);
        }
    }
    if (image != VK_NULL_HANDLE) vkDestroyImage(vk.device, image, nullptr);
    if (memory != VK_NULL_HANDLE) vkFreeMemory(vk.device, memory, nullptr);
}

ImportedCameraPreview* active_imported_camera_preview() {
    if (g_active_imported_camera_preview < 0) return nullptr;
    size_t index = static_cast<size_t>(g_active_imported_camera_preview);
    if (index >= g_imported_camera_preview_cache.size()) return nullptr;
    return &g_imported_camera_preview_cache[index];
}

int find_imported_camera_preview_cache_index(AHardwareBuffer* buffer) {
    for (size_t i = 0; i < g_imported_camera_preview_cache.size(); ++i) {
        if (g_imported_camera_preview_cache[i].buffer == buffer) {
            return static_cast<int>(i);
        }
    }
    return -1;
}

void evict_imported_camera_preview_if_needed(VulkanState& vk) {
    if (g_imported_camera_preview_cache.size() < kMaxImportedCameraPreviewCacheEntries) return;
    size_t victim = 0;
    uint64_t oldest = g_imported_camera_preview_cache[0].last_used_counter;
    for (size_t i = 1; i < g_imported_camera_preview_cache.size(); ++i) {
        if (g_imported_camera_preview_cache[i].last_used_counter < oldest) {
            oldest = g_imported_camera_preview_cache[i].last_used_counter;
            victim = i;
        }
    }
    destroy_imported_camera_preview_entry(vk, g_imported_camera_preview_cache[victim]);
    g_imported_camera_preview_cache.erase(g_imported_camera_preview_cache.begin() + static_cast<std::ptrdiff_t>(victim));
    if (g_active_imported_camera_preview == static_cast<int>(victim)) {
        g_active_imported_camera_preview = -1;
    } else if (g_active_imported_camera_preview > static_cast<int>(victim)) {
        g_active_imported_camera_preview -= 1;
    }
    g_gpu_preview.import_cache_evictions += 1;
}

bool import_hardware_buffer_preview_entry(
    VulkanState& vk,
    AHardwareBuffer* buffer,
    const AHardwareBuffer_Desc& desc,
    int width,
    int height,
    int64_t timestamp_ns,
    std::string& error
) {
    if (!vk.initialized || vk.device == VK_NULL_HANDLE || buffer == nullptr) {
        error = "Vulkan device or HardwareBuffer is unavailable";
        return false;
    }
    if (!vk.android_hardware_buffer_extensions) {
        error = "required Vulkan AHardwareBuffer extensions are unavailable";
        return false;
    }
    if (!ensure_preview_base_resources(vk)) {
        error = "Vulkan GPU preview base resources could not be created";
        return false;
    }
    evict_imported_camera_preview_if_needed(vk);

    auto get_ahb_properties = reinterpret_cast<PFN_vkGetAndroidHardwareBufferPropertiesANDROID>(
        vkGetDeviceProcAddr(vk.device, "vkGetAndroidHardwareBufferPropertiesANDROID")
    );
    if (get_ahb_properties == nullptr) {
        error = "vkGetAndroidHardwareBufferPropertiesANDROID is unavailable";
        return false;
    }

    VkAndroidHardwareBufferFormatPropertiesANDROID format_props{
        VK_STRUCTURE_TYPE_ANDROID_HARDWARE_BUFFER_FORMAT_PROPERTIES_ANDROID
    };
    VkAndroidHardwareBufferPropertiesANDROID buffer_props{
        VK_STRUCTURE_TYPE_ANDROID_HARDWARE_BUFFER_PROPERTIES_ANDROID
    };
    buffer_props.pNext = &format_props;
    VkResult props_result = get_ahb_properties(vk.device, buffer, &buffer_props);
    if (props_result != VK_SUCCESS) {
        char msg[128];
        std::snprintf(msg, sizeof(msg), "vkGetAndroidHardwareBufferPropertiesANDROID failed: %d", props_result);
        error = msg;
        return false;
    }

    VkExternalFormatANDROID external_format{VK_STRUCTURE_TYPE_EXTERNAL_FORMAT_ANDROID};
    external_format.externalFormat = format_props.externalFormat;

    VkExternalMemoryImageCreateInfo external_memory{
        VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_IMAGE_CREATE_INFO
    };
    external_memory.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_ANDROID_HARDWARE_BUFFER_BIT_ANDROID;
    external_memory.pNext = format_props.externalFormat != 0 ? &external_format : nullptr;

    VkImageCreateInfo image_info{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    image_info.pNext = &external_memory;
    image_info.imageType = VK_IMAGE_TYPE_2D;
    image_info.format = format_props.externalFormat != 0 ? VK_FORMAT_UNDEFINED : format_props.format;
    image_info.extent = {
        static_cast<uint32_t>(std::max(1, width)),
        static_cast<uint32_t>(std::max(1, height)),
        1
    };
    image_info.mipLevels = 1;
    image_info.arrayLayers = 1;
    image_info.samples = VK_SAMPLE_COUNT_1_BIT;
    image_info.tiling = VK_IMAGE_TILING_OPTIMAL;
    image_info.usage = VK_IMAGE_USAGE_SAMPLED_BIT;
    image_info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    image_info.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;

    VkImage image = VK_NULL_HANDLE;
    VkResult image_result = vkCreateImage(vk.device, &image_info, nullptr, &image);
    if (image_result != VK_SUCCESS) {
        char msg[128];
        std::snprintf(msg, sizeof(msg), "vkCreateImage for HardwareBuffer failed: %d", image_result);
        error = msg;
        return false;
    }

    uint32_t memory_type = find_memory_type(vk, buffer_props.memoryTypeBits, 0);
    if (memory_type == std::numeric_limits<uint32_t>::max()) {
        cleanup_imported_hardware_preview(vk, VK_NULL_HANDLE, VK_NULL_HANDLE, VK_NULL_HANDLE, VK_NULL_HANDLE, image);
        error = "no compatible memory type for imported HardwareBuffer";
        return false;
    }

    VkImportAndroidHardwareBufferInfoANDROID import_info{
        VK_STRUCTURE_TYPE_IMPORT_ANDROID_HARDWARE_BUFFER_INFO_ANDROID
    };
    import_info.buffer = buffer;
    VkMemoryDedicatedAllocateInfo dedicated_info{
        VK_STRUCTURE_TYPE_MEMORY_DEDICATED_ALLOCATE_INFO
    };
    dedicated_info.image = image;
    dedicated_info.pNext = &import_info;
    VkMemoryAllocateInfo allocate_info{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    allocate_info.pNext = &dedicated_info;
    allocate_info.allocationSize = buffer_props.allocationSize;
    allocate_info.memoryTypeIndex = memory_type;

    VkDeviceMemory memory = VK_NULL_HANDLE;
    VkResult alloc_result = vkAllocateMemory(vk.device, &allocate_info, nullptr, &memory);
    if (alloc_result != VK_SUCCESS) {
        cleanup_imported_hardware_preview(vk, VK_NULL_HANDLE, VK_NULL_HANDLE, VK_NULL_HANDLE, VK_NULL_HANDLE, image);
        char msg[128];
        std::snprintf(msg, sizeof(msg), "vkAllocateMemory imported HardwareBuffer failed: %d", alloc_result);
        error = msg;
        return false;
    }
    VkResult bind_result = vkBindImageMemory(vk.device, image, memory, 0);
    if (bind_result != VK_SUCCESS) {
        cleanup_imported_hardware_preview(vk, VK_NULL_HANDLE, VK_NULL_HANDLE, VK_NULL_HANDLE, memory, image);
        char msg[128];
        std::snprintf(msg, sizeof(msg), "vkBindImageMemory imported HardwareBuffer failed: %d", bind_result);
        error = msg;
        return false;
    }

    VkSamplerYcbcrConversion conversion = VK_NULL_HANDLE;
    if (format_props.externalFormat != 0) {
        VkExternalFormatANDROID conversion_external_format{VK_STRUCTURE_TYPE_EXTERNAL_FORMAT_ANDROID};
        conversion_external_format.externalFormat = format_props.externalFormat;
        VkSamplerYcbcrConversionCreateInfo conversion_info{
            VK_STRUCTURE_TYPE_SAMPLER_YCBCR_CONVERSION_CREATE_INFO
        };
        conversion_info.pNext = &conversion_external_format;
        conversion_info.format = VK_FORMAT_UNDEFINED;
        conversion_info.ycbcrModel = format_props.suggestedYcbcrModel;
        conversion_info.ycbcrRange = format_props.suggestedYcbcrRange;
        conversion_info.components = format_props.samplerYcbcrConversionComponents;
        conversion_info.xChromaOffset = format_props.suggestedXChromaOffset;
        conversion_info.yChromaOffset = format_props.suggestedYChromaOffset;
        conversion_info.chromaFilter = VK_FILTER_LINEAR;
        auto create_conversion = load_create_sampler_ycbcr_conversion(vk);
        if (create_conversion == nullptr) {
            cleanup_imported_hardware_preview(vk, VK_NULL_HANDLE, VK_NULL_HANDLE, VK_NULL_HANDLE, memory, image);
            error = "vkCreateSamplerYcbcrConversionKHR is unavailable";
            return false;
        }
        VkResult conversion_result = create_conversion(vk.device, &conversion_info, nullptr, &conversion);
        if (conversion_result != VK_SUCCESS) {
            cleanup_imported_hardware_preview(vk, VK_NULL_HANDLE, VK_NULL_HANDLE, VK_NULL_HANDLE, memory, image);
            char msg[128];
            std::snprintf(msg, sizeof(msg), "VkSamplerYcbcrConversionCreateInfo failed: %d", conversion_result);
            error = msg;
            return false;
        }
    }

    VkSamplerYcbcrConversionInfo sampler_conversion_info{
        VK_STRUCTURE_TYPE_SAMPLER_YCBCR_CONVERSION_INFO
    };
    sampler_conversion_info.conversion = conversion;
    VkSamplerCreateInfo sampler_info{VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO};
    sampler_info.pNext = conversion != VK_NULL_HANDLE ? &sampler_conversion_info : nullptr;
    sampler_info.magFilter = VK_FILTER_LINEAR;
    sampler_info.minFilter = VK_FILTER_LINEAR;
    sampler_info.mipmapMode = VK_SAMPLER_MIPMAP_MODE_NEAREST;
    sampler_info.addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    sampler_info.addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    sampler_info.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    sampler_info.maxLod = 1.0f;

    VkSampler sampler = VK_NULL_HANDLE;
    VkResult sampler_result = vkCreateSampler(vk.device, &sampler_info, nullptr, &sampler);
    if (sampler_result != VK_SUCCESS) {
        cleanup_imported_hardware_preview(vk, VK_NULL_HANDLE, VK_NULL_HANDLE, conversion, memory, image);
        char msg[128];
        std::snprintf(msg, sizeof(msg), "vkCreateSampler for HardwareBuffer failed: %d", sampler_result);
        error = msg;
        return false;
    }

    VkSamplerYcbcrConversionInfo view_conversion_info{
        VK_STRUCTURE_TYPE_SAMPLER_YCBCR_CONVERSION_INFO
    };
    view_conversion_info.conversion = conversion;
    VkImageViewCreateInfo view_info{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
    view_info.pNext = conversion != VK_NULL_HANDLE ? &view_conversion_info : nullptr;
    view_info.image = image;
    view_info.viewType = VK_IMAGE_VIEW_TYPE_2D;
    view_info.format = format_props.externalFormat != 0 ? VK_FORMAT_UNDEFINED : format_props.format;
    view_info.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    view_info.subresourceRange.baseMipLevel = 0;
    view_info.subresourceRange.levelCount = 1;
    view_info.subresourceRange.baseArrayLayer = 0;
    view_info.subresourceRange.layerCount = 1;

    VkImageView image_view = VK_NULL_HANDLE;
    VkResult view_result = vkCreateImageView(vk.device, &view_info, nullptr, &image_view);
    if (view_result != VK_SUCCESS) {
        cleanup_imported_hardware_preview(vk, VK_NULL_HANDLE, sampler, conversion, memory, image);
        char msg[128];
        std::snprintf(msg, sizeof(msg), "vkCreateImageView for HardwareBuffer failed: %d", view_result);
        error = msg;
        return false;
    }

    VkCommandBuffer transition_cmd = vk.command_buffers.empty() ? VK_NULL_HANDLE : vk.command_buffers[0];
    if (transition_cmd == VK_NULL_HANDLE) {
        cleanup_imported_hardware_preview(vk, image_view, sampler, conversion, memory, image);
        error = "no command buffer available for HardwareBuffer image transition";
        return false;
    }
    vkResetCommandBuffer(transition_cmd, 0);
    VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    if (vkBeginCommandBuffer(transition_cmd, &begin) != VK_SUCCESS) {
        cleanup_imported_hardware_preview(vk, image_view, sampler, conversion, memory, image);
        error = "failed to begin HardwareBuffer transition command";
        return false;
    }
    image_barrier(transition_cmd, image, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
    if (vkEndCommandBuffer(transition_cmd) != VK_SUCCESS) {
        cleanup_imported_hardware_preview(vk, image_view, sampler, conversion, memory, image);
        error = "failed to end HardwareBuffer transition command";
        return false;
    }
    VkSubmitInfo transition_submit{VK_STRUCTURE_TYPE_SUBMIT_INFO};
    transition_submit.commandBufferCount = 1;
    transition_submit.pCommandBuffers = &transition_cmd;
    if (vkQueueSubmit(vk.queue, 1, &transition_submit, VK_NULL_HANDLE) != VK_SUCCESS) {
        cleanup_imported_hardware_preview(vk, image_view, sampler, conversion, memory, image);
        error = "failed to submit HardwareBuffer transition";
        return false;
    }
    vkQueueWaitIdle(vk.queue);

    VkDescriptorSetLayout descriptor_layout = VK_NULL_HANDLE;
    if (!create_texture_descriptor_set_layout(vk, &sampler, descriptor_layout)) {
        cleanup_imported_hardware_preview(vk, image_view, sampler, conversion, memory, image);
        error = "failed to create immutable HardwareBuffer descriptor set layout";
        return false;
    }
    VkDescriptorPoolSize camera_pool_size{};
    camera_pool_size.type = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    camera_pool_size.descriptorCount = 1;
    VkDescriptorPoolCreateInfo camera_pool_info{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
    camera_pool_info.maxSets = 1;
    camera_pool_info.poolSizeCount = 1;
    camera_pool_info.pPoolSizes = &camera_pool_size;
    VkDescriptorPool camera_descriptor_pool = VK_NULL_HANDLE;
    if (vkCreateDescriptorPool(vk.device, &camera_pool_info, nullptr, &camera_descriptor_pool) != VK_SUCCESS) {
        vkDestroyDescriptorSetLayout(vk.device, descriptor_layout, nullptr);
        cleanup_imported_hardware_preview(vk, image_view, sampler, conversion, memory, image);
        error = "failed to create HardwareBuffer descriptor pool";
        return false;
    }
    VkDescriptorSet descriptor_set = VK_NULL_HANDLE;
    VkDescriptorSetAllocateInfo camera_set_info{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
    camera_set_info.descriptorPool = camera_descriptor_pool;
    camera_set_info.descriptorSetCount = 1;
    camera_set_info.pSetLayouts = &descriptor_layout;
    if (vkAllocateDescriptorSets(vk.device, &camera_set_info, &descriptor_set) != VK_SUCCESS) {
        vkDestroyDescriptorPool(vk.device, camera_descriptor_pool, nullptr);
        vkDestroyDescriptorSetLayout(vk.device, descriptor_layout, nullptr);
        cleanup_imported_hardware_preview(vk, image_view, sampler, conversion, memory, image);
        error = "failed to allocate HardwareBuffer descriptor set";
        return false;
    }
    update_texture_descriptor(vk, descriptor_set, image_view, sampler);
    VkShaderModule fragment_shader = create_shader_module(vk, kCameraFragSpv, sizeof(kCameraFragSpv) / sizeof(uint32_t));
    if (fragment_shader == VK_NULL_HANDLE) {
        vkDestroyDescriptorPool(vk.device, camera_descriptor_pool, nullptr);
        vkDestroyDescriptorSetLayout(vk.device, descriptor_layout, nullptr);
        cleanup_imported_hardware_preview(vk, image_view, sampler, conversion, memory, image);
        error = "failed to create camera fragment shader module";
        return false;
    }
    VkPipelineLayout pipeline_layout = VK_NULL_HANDLE;
    VkPipeline pipeline = VK_NULL_HANDLE;
    if (!create_fullscreen_pipeline(
            vk,
            descriptor_layout,
            fragment_shader,
            false,
            true,
            pipeline_layout,
            pipeline,
            vk.camera_intermediate_render_pass != VK_NULL_HANDLE ? vk.camera_intermediate_render_pass : vk.render_pass)) {
        vkDestroyShaderModule(vk.device, fragment_shader, nullptr);
        vkDestroyDescriptorPool(vk.device, camera_descriptor_pool, nullptr);
        vkDestroyDescriptorSetLayout(vk.device, descriptor_layout, nullptr);
        cleanup_imported_hardware_preview(vk, image_view, sampler, conversion, memory, image);
        error = "failed to create HardwareBuffer graphics pipeline";
        return false;
    }

    AHardwareBuffer_acquire(buffer);
    ImportedCameraPreview entry{};
    entry.ready = true;
    entry.width = static_cast<int>(desc.width > 0 ? desc.width : static_cast<uint32_t>(width));
    entry.height = static_cast<int>(desc.height > 0 ? desc.height : static_cast<uint32_t>(height));
    entry.rotation_degrees = ((g_hardware_primary.rotation_degrees % 360) + 360) % 360;
    entry.timestamp_ns = timestamp_ns;
    entry.last_used_counter = ++g_imported_camera_preview_use_counter;
    entry.buffer = buffer;
    entry.image = image;
    entry.memory = memory;
    entry.image_view = image_view;
    entry.conversion = conversion;
    entry.sampler = sampler;
    entry.descriptor_pool = camera_descriptor_pool;
    entry.descriptor_set_layout = descriptor_layout;
    entry.pipeline_layout = pipeline_layout;
    entry.pipeline = pipeline;
    entry.fragment_shader = fragment_shader;
    entry.descriptor_set = descriptor_set;
    g_imported_camera_preview_cache.push_back(entry);
    g_active_imported_camera_preview = static_cast<int>(g_imported_camera_preview_cache.size() - 1);
    g_gpu_preview.import_cache_entries = static_cast<uint32_t>(g_imported_camera_preview_cache.size());
    return true;
}

bool ensure_staging_buffer(VulkanState& vk, VkDeviceSize size) {
    if (vk.staging_buffer != VK_NULL_HANDLE && vk.staging_capacity >= size) return true;
    if (vk.staging_buffer != VK_NULL_HANDLE) {
        vkDestroyBuffer(vk.device, vk.staging_buffer, nullptr);
        vk.staging_buffer = VK_NULL_HANDLE;
    }
    if (vk.staging_memory != VK_NULL_HANDLE) {
        vkFreeMemory(vk.device, vk.staging_memory, nullptr);
        vk.staging_memory = VK_NULL_HANDLE;
    }
    VkBufferCreateInfo bci{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    bci.size = size;
    bci.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
    bci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    if (vkCreateBuffer(vk.device, &bci, nullptr, &vk.staging_buffer) != VK_SUCCESS) return false;
    VkMemoryRequirements req{};
    vkGetBufferMemoryRequirements(vk.device, vk.staging_buffer, &req);
    uint32_t memory_type = find_memory_type(vk, req.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    if (memory_type == std::numeric_limits<uint32_t>::max()) return false;
    VkMemoryAllocateInfo alloc{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    alloc.allocationSize = req.size;
    alloc.memoryTypeIndex = memory_type;
    if (vkAllocateMemory(vk.device, &alloc, nullptr, &vk.staging_memory) != VK_SUCCESS) return false;
    if (vkBindBufferMemory(vk.device, vk.staging_buffer, vk.staging_memory, 0) != VK_SUCCESS) return false;
    vk.staging_capacity = size;
    return true;
}

// Each presentation slot owns its upload buffer. The slot fence is waited before
// this helper is called, so resizing or rewriting the buffer cannot race the GPU.
bool ensure_frame_staging_buffer(VulkanState& vk, VulkanState::PreviewFrameSync& frame, VkDeviceSize size) {
    if (frame.staging_buffer != VK_NULL_HANDLE && frame.staging_capacity >= size) return true;
    if (frame.staging_buffer != VK_NULL_HANDLE) {
        vkDestroyBuffer(vk.device, frame.staging_buffer, nullptr);
        frame.staging_buffer = VK_NULL_HANDLE;
    }
    if (frame.staging_memory != VK_NULL_HANDLE) {
        vkFreeMemory(vk.device, frame.staging_memory, nullptr);
        frame.staging_memory = VK_NULL_HANDLE;
    }
    VkBufferCreateInfo bci{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    bci.size = size;
    bci.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
    bci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    if (vkCreateBuffer(vk.device, &bci, nullptr, &frame.staging_buffer) != VK_SUCCESS) return false;
    VkMemoryRequirements req{};
    vkGetBufferMemoryRequirements(vk.device, frame.staging_buffer, &req);
    uint32_t memory_type = find_memory_type(vk, req.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    if (memory_type == std::numeric_limits<uint32_t>::max()) return false;
    VkMemoryAllocateInfo alloc{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    alloc.allocationSize = req.size;
    alloc.memoryTypeIndex = memory_type;
    if (vkAllocateMemory(vk.device, &alloc, nullptr, &frame.staging_memory) != VK_SUCCESS) return false;
    if (vkBindBufferMemory(vk.device, frame.staging_buffer, frame.staging_memory, 0) != VK_SUCCESS) return false;
    frame.staging_capacity = size;
    return true;
}

void image_barrier(VkCommandBuffer cmd, VkImage image, VkImageLayout old_layout, VkImageLayout new_layout) {
    VkImageMemoryBarrier barrier{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};
    barrier.oldLayout = old_layout;
    barrier.newLayout = new_layout;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.image = image;
    barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    barrier.subresourceRange.baseMipLevel = 0;
    barrier.subresourceRange.levelCount = 1;
    barrier.subresourceRange.baseArrayLayer = 0;
    barrier.subresourceRange.layerCount = 1;
    barrier.srcAccessMask = 0;
    barrier.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    VkPipelineStageFlags src_stage = VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT;
    VkPipelineStageFlags dst_stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
    if (new_layout == VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL) {
        barrier.srcAccessMask = old_layout == VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL ? VK_ACCESS_SHADER_READ_BIT : 0;
        barrier.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        src_stage = old_layout == VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL ? VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT : VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT;
        dst_stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
    } else if (new_layout == VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL) {
        barrier.srcAccessMask =
            old_layout == VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL ? VK_ACCESS_TRANSFER_WRITE_BIT :
            old_layout == VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL ? VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT :
            0;
        barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
        src_stage =
            old_layout == VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL ? VK_PIPELINE_STAGE_TRANSFER_BIT :
            old_layout == VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL ? VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT :
            VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT;
        dst_stage = VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT;
    } else if (new_layout == VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL) {
        barrier.srcAccessMask = old_layout == VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL ? VK_ACCESS_SHADER_READ_BIT : 0;
        barrier.dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
        src_stage = old_layout == VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL ? VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT : VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT;
        dst_stage = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    } else if (new_layout == VK_IMAGE_LAYOUT_PRESENT_SRC_KHR) {
        barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        barrier.dstAccessMask = 0;
        src_stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
        dst_stage = VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT;
    }
    vkCmdPipelineBarrier(cmd, src_stage, dst_stage, 0, 0, nullptr, 0, nullptr, 1, &barrier);
}

VkShaderModule create_shader_module(VulkanState& vk, const uint32_t* words, size_t word_count) {
    VkShaderModuleCreateInfo info{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    info.codeSize = word_count * sizeof(uint32_t);
    info.pCode = words;
    VkShaderModule module = VK_NULL_HANDLE;
    if (vkCreateShaderModule(vk.device, &info, nullptr, &module) != VK_SUCCESS) return VK_NULL_HANDLE;
    return module;
}

bool ensure_preview_descriptor_pool(VulkanState& vk) {
    if (vk.preview_descriptor_pool != VK_NULL_HANDLE) return true;
    VkDescriptorPoolSize size{};
    size.type = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    size.descriptorCount = 16;
    VkDescriptorPoolCreateInfo info{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
    info.maxSets = 16;
    info.poolSizeCount = 1;
    info.pPoolSizes = &size;
    return vkCreateDescriptorPool(vk.device, &info, nullptr, &vk.preview_descriptor_pool) == VK_SUCCESS;
}

bool create_texture_descriptor_set_layout(VulkanState& vk, const VkSampler* immutable_sampler, VkDescriptorSetLayout& layout) {
    VkDescriptorSetLayoutBinding binding{};
    binding.binding = 0;
    binding.descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    binding.descriptorCount = 1;
    binding.stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
    binding.pImmutableSamplers = immutable_sampler;
    VkDescriptorSetLayoutCreateInfo info{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    info.bindingCount = 1;
    info.pBindings = &binding;
    return vkCreateDescriptorSetLayout(vk.device, &info, nullptr, &layout) == VK_SUCCESS;
}

bool allocate_texture_descriptor_set(VulkanState& vk, VkDescriptorSetLayout layout, VkDescriptorSet& set) {
    if (!ensure_preview_descriptor_pool(vk)) return false;
    VkDescriptorSetAllocateInfo info{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
    info.descriptorPool = vk.preview_descriptor_pool;
    info.descriptorSetCount = 1;
    info.pSetLayouts = &layout;
    return vkAllocateDescriptorSets(vk.device, &info, &set) == VK_SUCCESS;
}

void update_texture_descriptor(VulkanState& vk, VkDescriptorSet set, VkImageView view, VkSampler sampler) {
    VkDescriptorImageInfo image_info{};
    image_info.sampler = sampler;
    image_info.imageView = view;
    image_info.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    VkWriteDescriptorSet write{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET};
    write.dstSet = set;
    write.dstBinding = 0;
    write.descriptorCount = 1;
    write.descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    write.pImageInfo = &image_info;
    vkUpdateDescriptorSets(vk.device, 1, &write, 0, nullptr);
}

bool create_fullscreen_pipeline(
    VulkanState& vk,
    VkDescriptorSetLayout descriptor_layout,
    VkShaderModule fragment_shader,
    bool alpha_blend,
    bool camera_push_constants,
    VkPipelineLayout& pipeline_layout,
    VkPipeline& pipeline,
    VkRenderPass render_pass
) {
    VkPipelineShaderStageCreateInfo stages[2]{};
    stages[0].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
    stages[0].module = vk.fullscreen_vertex_shader;
    stages[0].pName = "main";
    stages[1].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    stages[1].module = fragment_shader;
    stages[1].pName = "main";

    VkPushConstantRange push_range{};
    push_range.stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
    push_range.offset = 0;
    push_range.size = sizeof(CameraPushConstants);

    VkPipelineLayoutCreateInfo layout_info{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    layout_info.setLayoutCount = 1;
    layout_info.pSetLayouts = &descriptor_layout;
    layout_info.pushConstantRangeCount = camera_push_constants ? 1 : 0;
    layout_info.pPushConstantRanges = camera_push_constants ? &push_range : nullptr;
    if (vkCreatePipelineLayout(vk.device, &layout_info, nullptr, &pipeline_layout) != VK_SUCCESS) return false;

    VkPipelineVertexInputStateCreateInfo vertex_input{VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
    VkPipelineInputAssemblyStateCreateInfo input_assembly{VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO};
    input_assembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    VkViewport viewport{};
    viewport.x = 0.0f;
    viewport.y = 0.0f;
    viewport.width = static_cast<float>(vk.extent.width);
    viewport.height = static_cast<float>(vk.extent.height);
    viewport.minDepth = 0.0f;
    viewport.maxDepth = 1.0f;
    VkRect2D scissor{};
    scissor.offset = {0, 0};
    scissor.extent = vk.extent;
    VkPipelineViewportStateCreateInfo viewport_state{VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO};
    viewport_state.viewportCount = 1;
    viewport_state.pViewports = &viewport;
    viewport_state.scissorCount = 1;
    viewport_state.pScissors = &scissor;
    VkPipelineRasterizationStateCreateInfo raster{VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO};
    raster.polygonMode = VK_POLYGON_MODE_FILL;
    raster.cullMode = VK_CULL_MODE_NONE;
    raster.frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE;
    raster.lineWidth = 1.0f;
    VkPipelineMultisampleStateCreateInfo multisample{VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO};
    multisample.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;
    VkPipelineColorBlendAttachmentState blend{};
    blend.colorWriteMask = VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT | VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;
    blend.blendEnable = alpha_blend ? VK_TRUE : VK_FALSE;
    blend.srcColorBlendFactor = VK_BLEND_FACTOR_SRC_ALPHA;
    blend.dstColorBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;
    blend.colorBlendOp = VK_BLEND_OP_ADD;
    blend.srcAlphaBlendFactor = VK_BLEND_FACTOR_ONE;
    blend.dstAlphaBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;
    blend.alphaBlendOp = VK_BLEND_OP_ADD;
    VkPipelineColorBlendStateCreateInfo blend_state{VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO};
    blend_state.attachmentCount = 1;
    blend_state.pAttachments = &blend;
    VkGraphicsPipelineCreateInfo pipeline_info{VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO};
    pipeline_info.stageCount = 2;
    pipeline_info.pStages = stages;
    pipeline_info.pVertexInputState = &vertex_input;
    pipeline_info.pInputAssemblyState = &input_assembly;
    pipeline_info.pViewportState = &viewport_state;
    pipeline_info.pRasterizationState = &raster;
    pipeline_info.pMultisampleState = &multisample;
    pipeline_info.pColorBlendState = &blend_state;
    pipeline_info.layout = pipeline_layout;
    pipeline_info.renderPass = render_pass != VK_NULL_HANDLE ? render_pass : vk.render_pass;
    pipeline_info.subpass = 0;
    if (vkCreateGraphicsPipelines(vk.device, VK_NULL_HANDLE, 1, &pipeline_info, nullptr, &pipeline) != VK_SUCCESS) {
        vkDestroyPipelineLayout(vk.device, pipeline_layout, nullptr);
        pipeline_layout = VK_NULL_HANDLE;
        return false;
    }
    return true;
}

bool create_image_2d(
    VulkanState& vk,
    int width,
    int height,
    VkFormat format,
    VkImageUsageFlags usage,
    VkImage& image,
    VkDeviceMemory& memory
) {
    VkImageCreateInfo image_info{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    image_info.imageType = VK_IMAGE_TYPE_2D;
    image_info.format = format;
    image_info.extent = {static_cast<uint32_t>(std::max(1, width)), static_cast<uint32_t>(std::max(1, height)), 1};
    image_info.mipLevels = 1;
    image_info.arrayLayers = 1;
    image_info.samples = VK_SAMPLE_COUNT_1_BIT;
    image_info.tiling = VK_IMAGE_TILING_OPTIMAL;
    image_info.usage = usage;
    image_info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    image_info.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    if (vkCreateImage(vk.device, &image_info, nullptr, &image) != VK_SUCCESS) return false;
    VkMemoryRequirements req{};
    vkGetImageMemoryRequirements(vk.device, image, &req);
    uint32_t memory_type = find_memory_type(vk, req.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    if (memory_type == std::numeric_limits<uint32_t>::max()) {
        vkDestroyImage(vk.device, image, nullptr);
        image = VK_NULL_HANDLE;
        return false;
    }
    VkMemoryAllocateInfo alloc{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    alloc.allocationSize = req.size;
    alloc.memoryTypeIndex = memory_type;
    if (vkAllocateMemory(vk.device, &alloc, nullptr, &memory) != VK_SUCCESS) {
        vkDestroyImage(vk.device, image, nullptr);
        image = VK_NULL_HANDLE;
        return false;
    }
    if (vkBindImageMemory(vk.device, image, memory, 0) != VK_SUCCESS) {
        vkDestroyImage(vk.device, image, nullptr);
        vkFreeMemory(vk.device, memory, nullptr);
        image = VK_NULL_HANDLE;
        memory = VK_NULL_HANDLE;
        return false;
    }
    return true;
}

bool ensure_overlay_texture(VulkanState& vk, int width, int height) {
    if (vk.overlay_image != VK_NULL_HANDLE && vk.overlay_width == width && vk.overlay_height == height && vk.overlay_descriptor_set != VK_NULL_HANDLE) {
        return true;
    }
    if (vk.overlay_view != VK_NULL_HANDLE) {
        vkDestroyImageView(vk.device, vk.overlay_view, nullptr);
        vk.overlay_view = VK_NULL_HANDLE;
    }
    if (vk.overlay_sampler != VK_NULL_HANDLE) {
        vkDestroySampler(vk.device, vk.overlay_sampler, nullptr);
        vk.overlay_sampler = VK_NULL_HANDLE;
    }
    if (vk.overlay_image != VK_NULL_HANDLE) {
        vkDestroyImage(vk.device, vk.overlay_image, nullptr);
        vk.overlay_image = VK_NULL_HANDLE;
    }
    if (vk.overlay_memory != VK_NULL_HANDLE) {
        vkFreeMemory(vk.device, vk.overlay_memory, nullptr);
        vk.overlay_memory = VK_NULL_HANDLE;
    }
    vk.overlay_descriptor_set = VK_NULL_HANDLE;
    vk.overlay_uploaded = false;
    if (!create_image_2d(vk, width, height, VK_FORMAT_B8G8R8A8_UNORM, VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_SAMPLED_BIT, vk.overlay_image, vk.overlay_memory)) {
        return false;
    }
    VkImageViewCreateInfo view_info{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
    view_info.image = vk.overlay_image;
    view_info.viewType = VK_IMAGE_VIEW_TYPE_2D;
    view_info.format = VK_FORMAT_B8G8R8A8_UNORM;
    view_info.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    view_info.subresourceRange.levelCount = 1;
    view_info.subresourceRange.layerCount = 1;
    if (vkCreateImageView(vk.device, &view_info, nullptr, &vk.overlay_view) != VK_SUCCESS) return false;
    VkSamplerCreateInfo sampler_info{VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO};
    sampler_info.magFilter = VK_FILTER_LINEAR;
    sampler_info.minFilter = VK_FILTER_LINEAR;
    sampler_info.mipmapMode = VK_SAMPLER_MIPMAP_MODE_NEAREST;
    sampler_info.addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    sampler_info.addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    sampler_info.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    sampler_info.maxLod = 1.0f;
    if (vkCreateSampler(vk.device, &sampler_info, nullptr, &vk.overlay_sampler) != VK_SUCCESS) return false;
    if (!allocate_texture_descriptor_set(vk, vk.overlay_descriptor_set_layout, vk.overlay_descriptor_set)) return false;
    update_texture_descriptor(vk, vk.overlay_descriptor_set, vk.overlay_view, vk.overlay_sampler);
    vk.overlay_width = width;
    vk.overlay_height = height;
    return true;
}

bool upload_overlay_texture(VulkanState& vk, const std::vector<uint32_t>& pixels, int width, int height) {
    if (!ensure_overlay_texture(vk, width, height)) return false;
    VkDeviceSize byte_count = static_cast<VkDeviceSize>(pixels.size() * sizeof(uint32_t));
    if (!ensure_staging_buffer(vk, byte_count)) return false;
    void* mapped = nullptr;
    if (vkMapMemory(vk.device, vk.staging_memory, 0, byte_count, 0, &mapped) != VK_SUCCESS) return false;
    std::memcpy(mapped, pixels.data(), static_cast<size_t>(byte_count));
    vkUnmapMemory(vk.device, vk.staging_memory);
    VkCommandBuffer cmd = vk.command_buffers.empty() ? VK_NULL_HANDLE : vk.command_buffers[0];
    if (cmd == VK_NULL_HANDLE) return false;
    vkResetCommandBuffer(cmd, 0);
    VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    if (vkBeginCommandBuffer(cmd, &begin) != VK_SUCCESS) return false;
    VkImageLayout old_layout = vk.overlay_uploaded ? VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL : VK_IMAGE_LAYOUT_UNDEFINED;
    image_barrier(cmd, vk.overlay_image, old_layout, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    VkBufferImageCopy region{};
    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    region.imageSubresource.layerCount = 1;
    region.imageExtent = {static_cast<uint32_t>(width), static_cast<uint32_t>(height), 1};
    vkCmdCopyBufferToImage(cmd, vk.staging_buffer, vk.overlay_image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);
    image_barrier(cmd, vk.overlay_image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
    if (vkEndCommandBuffer(cmd) != VK_SUCCESS) return false;
    VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO};
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &cmd;
    if (vkQueueSubmit(vk.queue, 1, &submit, VK_NULL_HANDLE) != VK_SUCCESS) return false;
    vkQueueWaitIdle(vk.queue);
    vk.overlay_uploaded = true;
    return true;
}

bool prepare_overlay_texture_upload(
    VulkanState& vk,
    const std::vector<uint32_t>& pixels,
    int width,
    int height
) {
    if (!ensure_overlay_texture(vk, width, height)) return false;
    VkDeviceSize byte_count = static_cast<VkDeviceSize>(pixels.size() * sizeof(uint32_t));
    if (!ensure_staging_buffer(vk, byte_count)) return false;
    void* mapped = nullptr;
    if (vkMapMemory(vk.device, vk.staging_memory, 0, byte_count, 0, &mapped) != VK_SUCCESS) return false;
    std::memcpy(mapped, pixels.data(), static_cast<size_t>(byte_count));
    vkUnmapMemory(vk.device, vk.staging_memory);
    return true;
}

void record_overlay_texture_upload(VulkanState& vk, VkCommandBuffer cmd, int width, int height) {
    VkImageLayout old_layout = vk.overlay_uploaded
        ? VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL
        : VK_IMAGE_LAYOUT_UNDEFINED;
    image_barrier(cmd, vk.overlay_image, old_layout, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    VkBufferImageCopy region{};
    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    region.imageSubresource.layerCount = 1;
    region.imageExtent = {static_cast<uint32_t>(width), static_cast<uint32_t>(height), 1};
    vkCmdCopyBufferToImage(
        cmd,
        vk.staging_buffer,
        vk.overlay_image,
        VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
        1,
        &region
    );
    image_barrier(
        cmd,
        vk.overlay_image,
        VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
        VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL
    );
}

bool ensure_camera_intermediate_render_pass(VulkanState& vk) {
    if (vk.camera_intermediate_render_pass != VK_NULL_HANDLE) return true;
    VkAttachmentDescription color{};
    color.format = VK_FORMAT_B8G8R8A8_UNORM;
    color.samples = VK_SAMPLE_COUNT_1_BIT;
    color.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    color.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    color.stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    color.stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    color.initialLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    color.finalLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    VkAttachmentReference ref{};
    ref.attachment = 0;
    ref.layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    VkSubpassDescription subpass{};
    subpass.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    subpass.colorAttachmentCount = 1;
    subpass.pColorAttachments = &ref;
    VkSubpassDependency dependencies[2]{};
    dependencies[0].srcSubpass = VK_SUBPASS_EXTERNAL;
    dependencies[0].dstSubpass = 0;
    dependencies[0].srcStageMask = VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT;
    dependencies[0].dstStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    dependencies[0].srcAccessMask = VK_ACCESS_SHADER_READ_BIT;
    dependencies[0].dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
    dependencies[1].srcSubpass = 0;
    dependencies[1].dstSubpass = VK_SUBPASS_EXTERNAL;
    dependencies[1].srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    dependencies[1].dstStageMask = VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT;
    dependencies[1].srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
    dependencies[1].dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
    VkRenderPassCreateInfo info{VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO};
    info.attachmentCount = 1;
    info.pAttachments = &color;
    info.subpassCount = 1;
    info.pSubpasses = &subpass;
    info.dependencyCount = 2;
    info.pDependencies = dependencies;
    return vkCreateRenderPass(vk.device, &info, nullptr, &vk.camera_intermediate_render_pass) == VK_SUCCESS;
}

bool ensure_camera_intermediate_texture(VulkanState& vk, int width, int height) {
    if (vk.camera_intermediate_image != VK_NULL_HANDLE &&
        vk.camera_intermediate_width == width &&
        vk.camera_intermediate_height == height &&
        vk.camera_intermediate_descriptor_set != VK_NULL_HANDLE &&
        vk.camera_intermediate_framebuffer != VK_NULL_HANDLE &&
        vk.camera_intermediate_pipeline != VK_NULL_HANDLE) {
        return true;
    }
    destroy_camera_intermediate_resources(vk);
    if (!ensure_camera_intermediate_render_pass(vk)) return false;
    if (!create_image_2d(
            vk,
            width,
            height,
            VK_FORMAT_B8G8R8A8_UNORM,
            VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
            vk.camera_intermediate_image,
            vk.camera_intermediate_memory)) {
        return false;
    }
    VkImageViewCreateInfo view_info{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
    view_info.image = vk.camera_intermediate_image;
    view_info.viewType = VK_IMAGE_VIEW_TYPE_2D;
    view_info.format = VK_FORMAT_B8G8R8A8_UNORM;
    view_info.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    view_info.subresourceRange.levelCount = 1;
    view_info.subresourceRange.layerCount = 1;
    if (vkCreateImageView(vk.device, &view_info, nullptr, &vk.camera_intermediate_view) != VK_SUCCESS) return false;
    VkSamplerCreateInfo sampler_info{VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO};
    sampler_info.magFilter = VK_FILTER_LINEAR;
    sampler_info.minFilter = VK_FILTER_LINEAR;
    sampler_info.mipmapMode = VK_SAMPLER_MIPMAP_MODE_NEAREST;
    sampler_info.addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    sampler_info.addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    sampler_info.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    sampler_info.maxLod = 1.0f;
    if (vkCreateSampler(vk.device, &sampler_info, nullptr, &vk.camera_intermediate_sampler) != VK_SUCCESS) return false;
    if (!allocate_texture_descriptor_set(vk, vk.overlay_descriptor_set_layout, vk.camera_intermediate_descriptor_set)) return false;
    update_texture_descriptor(vk, vk.camera_intermediate_descriptor_set, vk.camera_intermediate_view, vk.camera_intermediate_sampler);
    VkFramebufferCreateInfo fb{VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO};
    fb.renderPass = vk.camera_intermediate_render_pass;
    fb.attachmentCount = 1;
    fb.pAttachments = &vk.camera_intermediate_view;
    fb.width = static_cast<uint32_t>(width);
    fb.height = static_cast<uint32_t>(height);
    fb.layers = 1;
    if (vkCreateFramebuffer(vk.device, &fb, nullptr, &vk.camera_intermediate_framebuffer) != VK_SUCCESS) return false;
    if (vk.camera_intermediate_pipeline == VK_NULL_HANDLE) {
        if (!create_fullscreen_pipeline(
                vk,
                vk.overlay_descriptor_set_layout,
                vk.overlay_fragment_shader,
                false,
                false,
                vk.camera_intermediate_pipeline_layout,
                vk.camera_intermediate_pipeline,
                vk.render_pass)) {
            return false;
        }
    }
    vk.camera_intermediate_width = width;
    vk.camera_intermediate_height = height;
    vk.camera_intermediate_ready = false;
    vk.camera_intermediate_timestamp_ns = 0;
        g_gpu_preview.intermediate_enabled = true;
        g_gpu_preview.intermediate_width = width;
        g_gpu_preview.intermediate_height = height;
        g_gpu_preview.downsample_filter = g_downsample_filter;
        g_gpu_preview.filter_preset = g_downsample_filter;
        g_gpu_preview.downsample_taps = g_downsample_taps;
        g_gpu_preview.filter_taps = g_downsample_taps;
        g_gpu_preview.downsample_strength = static_cast<double>(g_downsample_strength);
        g_gpu_preview.luma_smoothing = static_cast<double>(g_luma_smoothing);
        g_gpu_preview.chroma_smoothing = static_cast<double>(g_chroma_smoothing);
        g_gpu_preview.edge_preserve = static_cast<double>(g_edge_preserve);
        g_gpu_preview.color_mode = g_color_mode;
        g_gpu_preview.red_gain = static_cast<double>(g_red_gain);
        g_gpu_preview.green_gain = static_cast<double>(g_green_gain);
        g_gpu_preview.blue_gain = static_cast<double>(g_blue_gain);
        g_gpu_preview.color_brightness = static_cast<double>(g_color_brightness);
        g_gpu_preview.color_contrast = static_cast<double>(g_color_contrast);
        g_gpu_preview.intermediate_last_timestamp_ns = 0;
        g_gpu_preview.intermediate_last_error.clear();
        g_gpu_preview.downsample_last_error.clear();
    return true;
}

bool ensure_preview_base_resources(VulkanState& vk) {
    if (vk.preview_base_ready) return true;
    if (!ensure_preview_descriptor_pool(vk)) return false;
    if (vk.fullscreen_vertex_shader == VK_NULL_HANDLE) {
        vk.fullscreen_vertex_shader = create_shader_module(vk, kFullscreenVertSpv, sizeof(kFullscreenVertSpv) / sizeof(uint32_t));
        if (vk.fullscreen_vertex_shader == VK_NULL_HANDLE) return false;
    }
    if (vk.overlay_fragment_shader == VK_NULL_HANDLE) {
        vk.overlay_fragment_shader = create_shader_module(vk, kOverlayFragSpv, sizeof(kOverlayFragSpv) / sizeof(uint32_t));
        if (vk.overlay_fragment_shader == VK_NULL_HANDLE) return false;
    }
    if (vk.overlay_descriptor_set_layout == VK_NULL_HANDLE) {
        if (!create_texture_descriptor_set_layout(vk, nullptr, vk.overlay_descriptor_set_layout)) return false;
    }
    if (vk.overlay_pipeline == VK_NULL_HANDLE) {
        if (!create_fullscreen_pipeline(vk, vk.overlay_descriptor_set_layout, vk.overlay_fragment_shader, true, false, vk.overlay_pipeline_layout, vk.overlay_pipeline)) return false;
    }
    vk.preview_base_ready = true;
    return true;
}

CameraPushConstants camera_push_constants(const ImportedCameraPreview& camera, const VulkanState& vk) {
    int rotation = ((camera.rotation_degrees % 360) + 360) % 360;
    bool rotated = rotation == 90 || rotation == 270;
    double oriented_width = static_cast<double>(rotated ? camera.height : camera.width);
    double oriented_height = static_cast<double>(rotated ? camera.width : camera.height);
    double out_width = static_cast<double>(std::max<uint32_t>(1, vk.extent.width));
    double out_height = static_cast<double>(std::max<uint32_t>(1, vk.extent.height));
    double visible_w = 0.0;
    double visible_h = 0.0;
    if (g_camera_primary.cover_mode == "pixel_crop") {
        double pixel_w = std::min(out_width, oriented_width);
        double pixel_h = std::min(out_height, oriented_height);
        double cover_scale = std::max(out_width / std::max(1.0, oriented_width), out_height / std::max(1.0, oriented_height));
        double cover_w = out_width / std::max(0.0001, cover_scale);
        double cover_h = out_height / std::max(0.0001, cover_scale);
        double blend = std::max(0.0, std::min(1.0, static_cast<double>(g_crop_fit_blend)));
        visible_w = pixel_w + (cover_w - pixel_w) * blend;
        visible_h = pixel_h + (cover_h - pixel_h) * blend;
    } else {
        double scale = std::max(out_width / std::max(1.0, oriented_width), out_height / std::max(1.0, oriented_height));
        visible_w = out_width / scale;
        visible_h = out_height / scale;
    }
    CameraPushConstants constants{};
    constants.scale_x = static_cast<float>(visible_w / std::max(1.0, oriented_width));
    constants.scale_y = static_cast<float>(visible_h / std::max(1.0, oriented_height));
    constants.offset_x = static_cast<float>((oriented_width - visible_w) * 0.5 / std::max(1.0, oriented_width));
    constants.offset_y = static_cast<float>((oriented_height - visible_h) * 0.5 / std::max(1.0, oriented_height));
    constants.rotation_degrees = static_cast<float>(rotation);
    constants.luma_smoothing = g_luma_smoothing;
    constants.chroma_smoothing = g_chroma_smoothing;
    constants.edge_preserve = g_edge_preserve;
    constants.detail_boost = g_downsample_strength;
    constants.filter_mode = g_downsample_mode;
    constants.color_contrast = g_color_contrast;
    constants.red_gain = g_red_gain;
    constants.green_gain = g_green_gain;
    constants.blue_gain = g_blue_gain;
    constants.color_brightness = g_color_brightness;
    return constants;
}

std::string overlay_cache_key_for_scene(const ParsedScene& scene, int width, int height, int logical_width, int logical_height) {
    std::string key = std::to_string(width) + "x" + std::to_string(height) + "/" +
        std::to_string(logical_width) + "x" + std::to_string(logical_height) + "/";
    key += std::to_string(scene.rects.size()) + "," + std::to_string(scene.circles.size()) + "," + std::to_string(scene.texts.size());
    key += "/offset=" + std::to_string(scene.content_offset_x) + "," + std::to_string(scene.content_offset_y);
    for (const auto& text : scene.texts) {
        key += "|" + text.text + "@" + std::to_string(static_cast<int>(text.x)) + "," + std::to_string(static_cast<int>(text.y));
    }
    return key;
}

bool import_latest_hardware_buffer_for_preview(VulkanState& vk, std::string& error) {
    CameraHardwareBufferFrame& frame = g_hardware_primary;
    if (!frame.has_frame || frame.buffer == nullptr) {
        error = "no primary HardwareBuffer frame is available";
        return false;
    }
    int cache_index = find_imported_camera_preview_cache_index(frame.buffer);
    if (cache_index >= 0) {
        ImportedCameraPreview& cached = g_imported_camera_preview_cache[static_cast<size_t>(cache_index)];
        cached.timestamp_ns = frame.timestamp_ns;
        cached.rotation_degrees = ((frame.rotation_degrees % 360) + 360) % 360;
        cached.last_used_counter = ++g_imported_camera_preview_use_counter;
        g_active_imported_camera_preview = cache_index;
        g_gpu_preview.import_cache_hits += 1;
        g_gpu_preview.import_cache_entries = static_cast<uint32_t>(g_imported_camera_preview_cache.size());
        g_gpu_preview.last_import_cache_hit = true;
        g_gpu_preview.last_import_ms = 0.0;
        return true;
    }
    AHardwareBuffer_Desc desc{};
    AHardwareBuffer_describe(frame.buffer, &desc);
    const int64_t import_start_ns = monotonic_now_ns();
    std::string import_error;
    bool ok = import_hardware_buffer_preview_entry(
        vk,
        frame.buffer,
        desc,
        frame.width,
        frame.height,
        frame.timestamp_ns,
        import_error
    );
    const int64_t import_end_ns = monotonic_now_ns();
    g_gpu_preview.last_import_ms = static_cast<double>(import_end_ns - import_start_ns) / 1000000.0;
    g_gpu_preview.last_import_cache_hit = false;
    g_gpu_preview.import_cache_misses += 1;
    g_gpu_preview.import_cache_entries = static_cast<uint32_t>(g_imported_camera_preview_cache.size());
    if (!ok) {
        error = import_error.empty() ? "HardwareBuffer import failed on render thread" : import_error;
        return false;
    }
    g_gpu_preview.imports += 1;
    g_gpu_preview.imports_on_render_thread += 1;
    if (g_gpu_preview.first_import_mono_ns <= 0) {
        g_gpu_preview.first_import_mono_ns = import_end_ns;
    }
    g_gpu_preview.last_import_mono_ns = import_end_ns;
    g_gpu_preview.import_fps = fps_from_window(
        g_gpu_preview.imports,
        g_gpu_preview.first_import_mono_ns,
        g_gpu_preview.last_import_mono_ns
    );
    return true;
}

bool render_scene_gpu_preview(VulkanState& vk, const ParsedScene& scene, int logical_width, int logical_height, std::string& error) {
    const int64_t draw_start_ns = monotonic_now_ns();
    if (!ensure_vulkan(vk)) {
        error = "Vulkan is unavailable";
        return false;
    }
    if (vk.preview_frames.empty()) {
        error = "GPU preview frame sync resources are unavailable";
        return false;
    }
    uint32_t frame_slot = static_cast<uint32_t>(vk.frame_counter % vk.preview_frames.size());
    VulkanState::PreviewFrameSync& frame_sync = vk.preview_frames[frame_slot];
    g_gpu_preview.current_frame_slot = frame_slot;
    g_gpu_preview.frames_in_flight = static_cast<uint32_t>(vk.preview_frames.size());
    g_gpu_preview.sync_mode = "frames_in_flight";
    if (!wait_fence_for_preview(vk, frame_sync.in_flight, &g_gpu_preview.frame_fence_waits, false)) {
        error = "failed to wait for GPU preview frame fence";
        return false;
    }
    if (!ensure_preview_base_resources(vk)) {
        error = "GPU preview base resources are unavailable";
        return false;
    }
    int width = static_cast<int>(vk.extent.width);
    int height = static_cast<int>(vk.extent.height);
    if (!ensure_camera_intermediate_texture(vk, width, height)) {
        error = "failed to create display-sized camera intermediate texture";
        g_gpu_preview.intermediate_last_error = error;
        return false;
    }
    if (!import_latest_hardware_buffer_for_preview(vk, error)) {
        return false;
    }
    ImportedCameraPreview* camera_preview = active_imported_camera_preview();
    if (camera_preview == nullptr || !camera_preview->ready || camera_preview->pipeline == VK_NULL_HANDLE) {
        error = "imported HardwareBuffer preview is not ready";
        return false;
    }
    std::string overlay_key = overlay_cache_key_for_scene(scene, width, height, logical_width, logical_height);
    if (vk.overlay_descriptor_set != VK_NULL_HANDLE && vk.overlay_cache_key == overlay_key) {
        g_gpu_preview.overlay_cache_hits += 1;
    } else {
        auto overlay = rasterize_overlay_pixels(scene, width, height, logical_width, logical_height);
        if (!upload_overlay_texture(vk, overlay, width, height)) {
            error = "failed to upload HUD overlay texture";
            return false;
        }
        vk.overlay_cache_key = std::move(overlay_key);
        g_gpu_preview.overlay_uploads += 1;
    }

    uint32_t image_index = 0;
    VkResult acquire = vkAcquireNextImageKHR(vk.device, vk.swapchain, UINT64_MAX, frame_sync.image_available, VK_NULL_HANDLE, &image_index);
    if (acquire == VK_ERROR_OUT_OF_DATE_KHR || acquire == VK_SUBOPTIMAL_KHR) {
        destroy_swapchain(vk);
        error = "swapchain changed during GPU preview render";
        return false;
    }
    if (acquire != VK_SUCCESS) {
        char msg[128];
        std::snprintf(msg, sizeof(msg), "vkAcquireNextImageKHR failed for GPU preview: %d", acquire);
        error = msg;
        return false;
    }
    g_gpu_preview.acquired_image_index = image_index;
    if (image_index < vk.images_in_flight.size() && vk.images_in_flight[image_index] != VK_NULL_HANDLE) {
        if (!wait_fence_for_preview(vk, vk.images_in_flight[image_index], &g_gpu_preview.image_fence_waits, false)) {
            error = "failed to wait for acquired swapchain image fence";
            return false;
        }
    }
    if (image_index < vk.images_in_flight.size()) {
        vk.images_in_flight[image_index] = frame_sync.in_flight;
    }
    VkCommandBuffer cmd = vk.command_buffers[image_index];
    vkResetCommandBuffer(cmd, 0);
    VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    if (vkBeginCommandBuffer(cmd, &begin) != VK_SUCCESS) {
        error = "failed to begin GPU preview command buffer";
        return false;
    }

    bool update_intermediate = !vk.camera_intermediate_ready ||
        vk.camera_intermediate_timestamp_ns != camera_preview->timestamp_ns;
    if (update_intermediate) {
        const int64_t intermediate_start_ns = monotonic_now_ns();
        VkImageLayout old_layout = vk.camera_intermediate_ready
            ? VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL
            : VK_IMAGE_LAYOUT_UNDEFINED;
        image_barrier(
            cmd,
            vk.camera_intermediate_image,
            old_layout,
            VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL
        );
        VkClearValue camera_clear{};
        camera_clear.color.float32[0] = 0.0f;
        camera_clear.color.float32[1] = 0.0f;
        camera_clear.color.float32[2] = 0.0f;
        camera_clear.color.float32[3] = 1.0f;
        VkRenderPassBeginInfo camera_rp{VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO};
        camera_rp.renderPass = vk.camera_intermediate_render_pass;
        camera_rp.framebuffer = vk.camera_intermediate_framebuffer;
        camera_rp.renderArea.offset = {0, 0};
        camera_rp.renderArea.extent = vk.extent;
        camera_rp.clearValueCount = 1;
        camera_rp.pClearValues = &camera_clear;
        vkCmdBeginRenderPass(cmd, &camera_rp, VK_SUBPASS_CONTENTS_INLINE);
        vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, camera_preview->pipeline);
        vkCmdBindDescriptorSets(
            cmd,
            VK_PIPELINE_BIND_POINT_GRAPHICS,
            camera_preview->pipeline_layout,
            0,
            1,
            &camera_preview->descriptor_set,
            0,
            nullptr
        );
        CameraPushConstants push = camera_push_constants(*camera_preview, vk);
        vkCmdPushConstants(
            cmd,
            camera_preview->pipeline_layout,
            VK_SHADER_STAGE_FRAGMENT_BIT,
            0,
            sizeof(CameraPushConstants),
            &push
        );
        vkCmdDraw(cmd, 3, 1, 0, 0);
        vkCmdEndRenderPass(cmd);
        vk.camera_intermediate_ready = true;
        vk.camera_intermediate_timestamp_ns = camera_preview->timestamp_ns;
        g_gpu_preview.intermediate_updates += 1;
        g_gpu_preview.intermediate_last_timestamp_ns = camera_preview->timestamp_ns;
        g_gpu_preview.last_intermediate_ms =
            static_cast<double>(monotonic_now_ns() - intermediate_start_ns) / 1000000.0;
        g_gpu_preview.last_downsample_ms = g_gpu_preview.last_intermediate_ms;
        g_gpu_preview.last_filter_ms = g_gpu_preview.last_intermediate_ms;
        g_gpu_preview.intermediate_last_error.clear();
        g_gpu_preview.downsample_last_error.clear();
    } else {
        g_gpu_preview.intermediate_reuses += 1;
        g_gpu_preview.last_intermediate_ms = 0.0;
        g_gpu_preview.last_downsample_ms = 0.0;
        g_gpu_preview.last_filter_ms = 0.0;
    }

    VkClearValue clear{};
    clear.color.float32[0] = 0.0f;
    clear.color.float32[1] = 0.0f;
    clear.color.float32[2] = 0.0f;
    clear.color.float32[3] = 1.0f;
    VkRenderPassBeginInfo rp{VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO};
    rp.renderPass = vk.render_pass;
    rp.framebuffer = vk.framebuffers[image_index];
    rp.renderArea.offset = {0, 0};
    rp.renderArea.extent = vk.extent;
    rp.clearValueCount = 1;
    rp.pClearValues = &clear;
    vkCmdBeginRenderPass(cmd, &rp, VK_SUBPASS_CONTENTS_INLINE);

    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, vk.camera_intermediate_pipeline);
    vkCmdBindDescriptorSets(
        cmd,
        VK_PIPELINE_BIND_POINT_GRAPHICS,
        vk.camera_intermediate_pipeline_layout,
        0,
        1,
        &vk.camera_intermediate_descriptor_set,
        0,
        nullptr
    );
    vkCmdDraw(cmd, 3, 1, 0, 0);

    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, vk.overlay_pipeline);
    vkCmdBindDescriptorSets(
        cmd,
        VK_PIPELINE_BIND_POINT_GRAPHICS,
        vk.overlay_pipeline_layout,
        0,
        1,
        &vk.overlay_descriptor_set,
        0,
        nullptr
    );
    vkCmdDraw(cmd, 3, 1, 0, 0);
    vkCmdEndRenderPass(cmd);

    if (vkEndCommandBuffer(cmd) != VK_SUCCESS) {
        error = "failed to end GPU preview command buffer";
        return false;
    }
    VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO};
    submit.waitSemaphoreCount = 1;
    submit.pWaitSemaphores = &frame_sync.image_available;
    submit.pWaitDstStageMask = &wait_stage;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &cmd;
    submit.signalSemaphoreCount = 1;
    submit.pSignalSemaphores = &frame_sync.render_finished;
    if (vkResetFences(vk.device, 1, &frame_sync.in_flight) != VK_SUCCESS) {
        error = "failed to reset GPU preview render fence";
        return false;
    }
    if (vkQueueSubmit(vk.queue, 1, &submit, frame_sync.in_flight) != VK_SUCCESS) {
        error = "vkQueueSubmit failed for GPU preview";
        return false;
    }
    VkPresentInfoKHR present{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};
    present.waitSemaphoreCount = 1;
    present.pWaitSemaphores = &frame_sync.render_finished;
    present.swapchainCount = 1;
    present.pSwapchains = &vk.swapchain;
    present.pImageIndices = &image_index;
    VkResult pr = vkQueuePresentKHR(vk.queue, &present);
    if (pr != VK_SUCCESS && pr != VK_SUBOPTIMAL_KHR) {
        char msg[128];
        std::snprintf(msg, sizeof(msg), "vkQueuePresentKHR failed for GPU preview: %d", pr);
        error = msg;
        return false;
    }
    g_preview_gpu_ready = true;
    g_gpu_preview.status = "running";
    g_gpu_preview.width = camera_preview->width;
    g_gpu_preview.height = camera_preview->height;
    g_gpu_preview.timestamp_ns = camera_preview->timestamp_ns;
    g_gpu_preview.draws += 1;
    const int64_t draw_end_ns = monotonic_now_ns();
    if (g_gpu_preview.first_draw_mono_ns <= 0) {
        g_gpu_preview.first_draw_mono_ns = draw_end_ns;
    }
    g_gpu_preview.last_draw_mono_ns = draw_end_ns;
    g_gpu_preview.draw_fps = fps_from_window(
        g_gpu_preview.draws,
        g_gpu_preview.first_draw_mono_ns,
        g_gpu_preview.last_draw_mono_ns
    );
    g_gpu_preview.last_draw_ms = static_cast<double>(draw_end_ns - draw_start_ns) / 1000000.0;
    g_gpu_preview.last_error.clear();
    vk.current_frame_slot = (frame_slot + 1) % static_cast<uint32_t>(vk.preview_frames.size());
    vk.frame_counter += 1;
    return true;
}

bool render_scene_pixels(VulkanState& vk, const ParsedScene& scene, int logical_width, int logical_height) {
    if (!ensure_vulkan(vk)) return false;
    ImportedCameraPreview* active_preview = active_imported_camera_preview();
    if ((active_preview != nullptr && active_preview->ready) || g_hardware_primary.has_frame) {
        std::string gpu_error;
        if (render_scene_gpu_preview(vk, scene, logical_width, logical_height, gpu_error)) {
            return true;
        }
        active_preview = active_imported_camera_preview();
        int error_width = active_preview != nullptr ? active_preview->width : 0;
        int error_height = active_preview != nullptr ? active_preview->height : 0;
        int64_t error_timestamp = active_preview != nullptr ? active_preview->timestamp_ns : 0;
        set_gpu_preview_error(gpu_error.empty() ? "GPU preview draw failed" : gpu_error, error_width, error_height, error_timestamp);
        if (vk.swapchain == VK_NULL_HANDLE || vk.framebuffers.empty() || vk.command_buffers.empty()) {
            if (!create_swapchain(vk) || !create_render_resources(vk)) return false;
        }
    }
    g_preview_gpu_ready = false;
    int width = static_cast<int>(vk.extent.width);
    int height = static_cast<int>(vk.extent.height);
    auto pixels = rasterize_scene_pixels(scene, width, height, logical_width, logical_height);
    convert_bgra_pixels_for_swapchain(pixels, vk.swapchain_format);
    VkDeviceSize byte_count = static_cast<VkDeviceSize>(pixels.size() * sizeof(uint32_t));
    if (vk.preview_frames.empty()) return false;
    uint32_t frame_slot = static_cast<uint32_t>(vk.frame_counter % vk.preview_frames.size());
    VulkanState::PreviewFrameSync& frame_sync = vk.preview_frames[frame_slot];
    if (!wait_fence_for_preview(vk, frame_sync.in_flight, nullptr, false)) return false;
    if (!ensure_frame_staging_buffer(vk, frame_sync, byte_count)) return false;
    void* mapped = nullptr;
    if (vkMapMemory(vk.device, frame_sync.staging_memory, 0, byte_count, 0, &mapped) != VK_SUCCESS) return false;
    std::memcpy(mapped, pixels.data(), static_cast<size_t>(byte_count));
    vkUnmapMemory(vk.device, frame_sync.staging_memory);
    uint32_t image_index = 0;
    VkResult acquire = vkAcquireNextImageKHR(vk.device, vk.swapchain, UINT64_MAX, frame_sync.image_available, VK_NULL_HANDLE, &image_index);
    if (acquire == VK_ERROR_OUT_OF_DATE_KHR || acquire == VK_SUBOPTIMAL_KHR) {
        destroy_swapchain(vk);
        return create_swapchain(vk) && create_render_resources(vk) && render_scene_pixels(vk, scene, logical_width, logical_height);
    }
    if (acquire != VK_SUCCESS) return false;
    if (image_index < vk.images_in_flight.size() && vk.images_in_flight[image_index] != VK_NULL_HANDLE) {
        if (!wait_fence_for_preview(vk, vk.images_in_flight[image_index], nullptr, false)) return false;
    }
    if (image_index < vk.images_in_flight.size()) {
        vk.images_in_flight[image_index] = frame_sync.in_flight;
    }
    VkCommandBuffer cmd = vk.command_buffers[image_index];
    vkResetCommandBuffer(cmd, 0);
    VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    if (vkBeginCommandBuffer(cmd, &begin) != VK_SUCCESS) return false;
    image_barrier(cmd, vk.images[image_index], VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    VkBufferImageCopy region{};
    region.bufferOffset = 0;
    region.bufferRowLength = 0;
    region.bufferImageHeight = 0;
    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    region.imageSubresource.mipLevel = 0;
    region.imageSubresource.baseArrayLayer = 0;
    region.imageSubresource.layerCount = 1;
    region.imageOffset = {0, 0, 0};
    region.imageExtent = {vk.extent.width, vk.extent.height, 1};
    vkCmdCopyBufferToImage(cmd, frame_sync.staging_buffer, vk.images[image_index], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);
    image_barrier(cmd, vk.images[image_index], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);
    if (vkEndCommandBuffer(cmd) != VK_SUCCESS) return false;
    VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
    VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO};
    submit.waitSemaphoreCount = 1;
    submit.pWaitSemaphores = &frame_sync.image_available;
    submit.pWaitDstStageMask = &wait_stage;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &cmd;
    submit.signalSemaphoreCount = 1;
    submit.pSignalSemaphores = &frame_sync.render_finished;
    if (vkResetFences(vk.device, 1, &frame_sync.in_flight) != VK_SUCCESS) return false;
    if (vkQueueSubmit(vk.queue, 1, &submit, frame_sync.in_flight) != VK_SUCCESS) return false;
    VkPresentInfoKHR present{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};
    present.waitSemaphoreCount = 1;
    present.pWaitSemaphores = &frame_sync.render_finished;
    present.swapchainCount = 1;
    present.pSwapchains = &vk.swapchain;
    present.pImageIndices = &image_index;
    VkResult pr = vkQueuePresentKHR(vk.queue, &present);
    vk.current_frame_slot = (frame_slot + 1) % static_cast<uint32_t>(vk.preview_frames.size());
    vk.frame_counter += 1;
    return pr == VK_SUCCESS || pr == VK_SUBOPTIMAL_KHR;
}

bool render_rgba_matrix(
    VulkanState& vk,
    const std::vector<uint32_t>& pixels,
    int source_width,
    int source_height
) {
    if (source_width <= 0 || source_height <= 0) return false;
    if (pixels.size() != static_cast<size_t>(source_width) * static_cast<size_t>(source_height)) return false;
    if (!ensure_vulkan(vk) || vk.preview_frames.empty()) return false;
    if (!ensure_preview_base_resources(vk)) return false;

    // The matrix presenter reuses one staging buffer. Waiting on its previous
    // submission protects that buffer without stalling the entire Vulkan queue.
    uint32_t frame_slot = 0;
    VulkanState::PreviewFrameSync& frame_sync = vk.preview_frames[frame_slot];
    if (!wait_fence_for_preview(vk, frame_sync.in_flight, nullptr, false)) return false;
    if (!prepare_overlay_texture_upload(vk, pixels, source_width, source_height)) return false;

    uint32_t image_index = 0;
    VkResult acquire = vkAcquireNextImageKHR(
        vk.device,
        vk.swapchain,
        UINT64_MAX,
        frame_sync.image_available,
        VK_NULL_HANDLE,
        &image_index
    );
    if (acquire == VK_ERROR_OUT_OF_DATE_KHR || acquire == VK_SUBOPTIMAL_KHR) {
        destroy_swapchain(vk);
        return create_swapchain(vk) && create_render_resources(vk) &&
            render_rgba_matrix(vk, pixels, source_width, source_height);
    }
    if (acquire != VK_SUCCESS) return false;
    if (image_index < vk.images_in_flight.size() && vk.images_in_flight[image_index] != VK_NULL_HANDLE) {
        if (!wait_fence_for_preview(vk, vk.images_in_flight[image_index], nullptr, false)) return false;
    }
    if (image_index < vk.images_in_flight.size()) {
        vk.images_in_flight[image_index] = frame_sync.in_flight;
    }

    VkCommandBuffer cmd = vk.command_buffers[image_index];
    vkResetCommandBuffer(cmd, 0);
    VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    if (vkBeginCommandBuffer(cmd, &begin) != VK_SUCCESS) return false;
    record_overlay_texture_upload(vk, cmd, source_width, source_height);
    VkClearValue clear{};
    clear.color.float32[3] = 1.0f;
    VkRenderPassBeginInfo render_pass{VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO};
    render_pass.renderPass = vk.render_pass;
    render_pass.framebuffer = vk.framebuffers[image_index];
    render_pass.renderArea.offset = {0, 0};
    render_pass.renderArea.extent = vk.extent;
    render_pass.clearValueCount = 1;
    render_pass.pClearValues = &clear;
    vkCmdBeginRenderPass(cmd, &render_pass, VK_SUBPASS_CONTENTS_INLINE);
    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, vk.overlay_pipeline);
    vkCmdBindDescriptorSets(
        cmd,
        VK_PIPELINE_BIND_POINT_GRAPHICS,
        vk.overlay_pipeline_layout,
        0,
        1,
        &vk.overlay_descriptor_set,
        0,
        nullptr
    );
    vkCmdDraw(cmd, 3, 1, 0, 0);
    vkCmdEndRenderPass(cmd);
    if (vkEndCommandBuffer(cmd) != VK_SUCCESS) return false;

    VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO};
    submit.waitSemaphoreCount = 1;
    submit.pWaitSemaphores = &frame_sync.image_available;
    submit.pWaitDstStageMask = &wait_stage;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &cmd;
    submit.signalSemaphoreCount = 1;
    submit.pSignalSemaphores = &frame_sync.render_finished;
    if (vkResetFences(vk.device, 1, &frame_sync.in_flight) != VK_SUCCESS) return false;
    if (vkQueueSubmit(vk.queue, 1, &submit, frame_sync.in_flight) != VK_SUCCESS) return false;
    vk.overlay_uploaded = true;

    VkPresentInfoKHR present{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};
    present.waitSemaphoreCount = 1;
    present.pWaitSemaphores = &frame_sync.render_finished;
    present.swapchainCount = 1;
    present.pSwapchains = &vk.swapchain;
    present.pImageIndices = &image_index;
    VkResult result = vkQueuePresentKHR(vk.queue, &present);
    vk.current_frame_slot = frame_slot;
    vk.frame_counter += 1;
    return result == VK_SUCCESS || result == VK_SUBOPTIMAL_KHR;
}

bool render_clear(VulkanState& vk, Rgba color) {
    if (!ensure_vulkan(vk)) return false;
    if (vk.preview_frames.empty()) return false;
    uint32_t frame_slot = static_cast<uint32_t>(vk.frame_counter % vk.preview_frames.size());
    VulkanState::PreviewFrameSync& frame_sync = vk.preview_frames[frame_slot];
    if (!wait_fence_for_preview(vk, frame_sync.in_flight, nullptr, false)) return false;
    uint32_t image_index = 0;
    VkResult acquire = vkAcquireNextImageKHR(vk.device, vk.swapchain, UINT64_MAX, frame_sync.image_available, VK_NULL_HANDLE, &image_index);
    if (acquire == VK_ERROR_OUT_OF_DATE_KHR || acquire == VK_SUBOPTIMAL_KHR) {
        destroy_swapchain(vk);
        return create_swapchain(vk) && create_render_resources(vk) && render_clear(vk, color);
    }
    if (acquire != VK_SUCCESS) return false;
    if (image_index < vk.images_in_flight.size() && vk.images_in_flight[image_index] != VK_NULL_HANDLE) {
        if (!wait_fence_for_preview(vk, vk.images_in_flight[image_index], nullptr, false)) return false;
    }
    if (image_index < vk.images_in_flight.size()) {
        vk.images_in_flight[image_index] = frame_sync.in_flight;
    }
    VkCommandBuffer cmd = vk.command_buffers[image_index];
    vkResetCommandBuffer(cmd, 0);
    VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    if (vkBeginCommandBuffer(cmd, &begin) != VK_SUCCESS) return false;
    VkClearValue clear{};
    clear.color.float32[0] = static_cast<float>(color.r) / 255.0f;
    clear.color.float32[1] = static_cast<float>(color.g) / 255.0f;
    clear.color.float32[2] = static_cast<float>(color.b) / 255.0f;
    clear.color.float32[3] = static_cast<float>(color.a) / 255.0f;
    VkRenderPassBeginInfo rp{VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO};
    rp.renderPass = vk.render_pass;
    rp.framebuffer = vk.framebuffers[image_index];
    rp.renderArea.offset = {0, 0};
    rp.renderArea.extent = vk.extent;
    rp.clearValueCount = 1;
    rp.pClearValues = &clear;
    vkCmdBeginRenderPass(cmd, &rp, VK_SUBPASS_CONTENTS_INLINE);
    vkCmdEndRenderPass(cmd);
    if (vkEndCommandBuffer(cmd) != VK_SUCCESS) return false;
    VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO};
    submit.waitSemaphoreCount = 1;
    submit.pWaitSemaphores = &frame_sync.image_available;
    submit.pWaitDstStageMask = &wait_stage;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &cmd;
    submit.signalSemaphoreCount = 1;
    submit.pSignalSemaphores = &frame_sync.render_finished;
    if (vkResetFences(vk.device, 1, &frame_sync.in_flight) != VK_SUCCESS) return false;
    if (vkQueueSubmit(vk.queue, 1, &submit, frame_sync.in_flight) != VK_SUCCESS) return false;
    VkPresentInfoKHR present{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};
    present.waitSemaphoreCount = 1;
    present.pWaitSemaphores = &frame_sync.render_finished;
    present.swapchainCount = 1;
    present.pSwapchains = &vk.swapchain;
    present.pImageIndices = &image_index;
    VkResult pr = vkQueuePresentKHR(vk.queue, &present);
    vk.current_frame_slot = (frame_slot + 1) % static_cast<uint32_t>(vk.preview_frames.size());
    vk.frame_counter += 1;
    return pr == VK_SUCCESS || pr == VK_SUBOPTIMAL_KHR;
}

struct BurstPlaneInfo {
    int row_stride = 0;
    int pixel_stride = 1;
    int byte_count = 0;
};

struct BurstFrameInfo {
    int index = 0;
    std::string frame_path;
    std::string metadata_path;
};

struct BurstMetadata {
    int width = 0;
    int height = 0;
    std::array<BurstPlaneInfo, 3> planes;
};

std::string read_text_file(const std::string& path) {
    std::ifstream input(path);
    if (!input) return "";
    std::ostringstream ss;
    ss << input.rdbuf();
    return ss.str();
}

std::vector<uint8_t> read_binary_file(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) return {};
    input.seekg(0, std::ios::end);
    const auto size = input.tellg();
    if (size <= 0) return {};
    input.seekg(0, std::ios::beg);
    std::vector<uint8_t> bytes(static_cast<size_t>(size));
    input.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(size));
    return bytes;
}

bool write_binary_file(const std::string& path, const std::vector<uint8_t>& bytes) {
    std::ofstream out(path, std::ios::binary);
    if (!out) return false;
    out.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    return static_cast<bool>(out);
}

std::string json_escape(const std::string& value) {
    std::string out;
    out.reserve(value.size());
    for (char ch : value) {
        if (ch == '\\' || ch == '"') out.push_back('\\');
        if (ch == '\n') {
            out += "\\n";
        } else {
            out.push_back(ch);
        }
    }
    return out;
}

std::string processor_error_json(const std::string& message) {
    return "{\"status\":\"error\",\"mode\":\"sharpest_native\",\"error\":\"" + json_escape(message) + "\"}";
}

std::string jstring_to_string(JNIEnv* env, jstring value) {
    if (value == nullptr) return "";
    const char* raw = env->GetStringUTFChars(value, nullptr);
    if (raw == nullptr) return "";
    std::string out(raw);
    env->ReleaseStringUTFChars(value, raw);
    return out;
}

std::string json_array_for_key(const std::string& json, const std::string& key) {
    const auto key_pos = json.find("\"" + key + "\"");
    if (key_pos == std::string::npos) return "";
    const auto open = json.find('[', key_pos);
    if (open == std::string::npos) return "";
    int depth = 0;
    bool in_string = false;
    bool escaped = false;
    for (auto i = open; i < json.size(); ++i) {
        const char ch = json[i];
        if (in_string) {
            if (escaped) {
                escaped = false;
            } else if (ch == '\\') {
                escaped = true;
            } else if (ch == '"') {
                in_string = false;
            }
            continue;
        }
        if (ch == '"') {
            in_string = true;
        } else if (ch == '[') {
            depth += 1;
        } else if (ch == ']') {
            depth -= 1;
            if (depth == 0) return json.substr(open, i - open + 1);
        }
    }
    return "";
}

std::vector<std::string> top_level_objects(const std::string& array_json) {
    std::vector<std::string> out;
    int depth = 0;
    bool in_string = false;
    bool escaped = false;
    std::string::size_type start = std::string::npos;
    for (std::string::size_type i = 0; i < array_json.size(); ++i) {
        const char ch = array_json[i];
        if (in_string) {
            if (escaped) {
                escaped = false;
            } else if (ch == '\\') {
                escaped = true;
            } else if (ch == '"') {
                in_string = false;
            }
            continue;
        }
        if (ch == '"') {
            in_string = true;
        } else if (ch == '{') {
            if (depth == 0) start = i;
            depth += 1;
        } else if (ch == '}') {
            depth -= 1;
            if (depth == 0 && start != std::string::npos) {
                out.push_back(array_json.substr(start, i - start + 1));
                start = std::string::npos;
            }
        }
    }
    return out;
}

std::vector<BurstFrameInfo> parse_burst_frames(const std::string& manifest) {
    std::vector<BurstFrameInfo> frames;
    for (const auto& item : top_level_objects(json_array_for_key(manifest, "frames"))) {
        BurstFrameInfo frame;
        frame.index = static_cast<int>(parse_number_key(item, "index", static_cast<double>(frames.size())));
        frame.frame_path = parse_string_key(item, "frame_path");
        frame.metadata_path = parse_string_key(item, "metadata_path");
        if (!frame.frame_path.empty() && !frame.metadata_path.empty()) {
            frames.push_back(frame);
        }
    }
    return frames;
}

BurstMetadata parse_burst_metadata(const std::string& metadata_json) {
    BurstMetadata metadata;
    metadata.width = static_cast<int>(parse_number_key(metadata_json, "width", 0.0));
    metadata.height = static_cast<int>(parse_number_key(metadata_json, "height", 0.0));
    const auto plane_objects = top_level_objects(json_array_for_key(metadata_json, "planes"));
    for (size_t i = 0; i < plane_objects.size() && i < metadata.planes.size(); ++i) {
        metadata.planes[i].row_stride = static_cast<int>(parse_number_key(plane_objects[i], "row_stride", 0.0));
        metadata.planes[i].pixel_stride = static_cast<int>(parse_number_key(plane_objects[i], "pixel_stride", 1.0));
        metadata.planes[i].byte_count = static_cast<int>(parse_number_key(plane_objects[i], "byte_count", 0.0));
    }
    return metadata;
}

uint8_t sample_burst_plane(
    const std::vector<uint8_t>& bytes,
    int offset,
    const BurstPlaneInfo& plane,
    int row,
    int col,
    uint8_t fallback
) {
    const int idx = offset + row * plane.row_stride + col * plane.pixel_stride;
    if (idx < 0 || static_cast<size_t>(idx) >= bytes.size()) return fallback;
    return bytes[static_cast<size_t>(idx)];
}

double score_yuv_luma_sharpness(const std::vector<uint8_t>& bytes, const BurstMetadata& metadata) {
    const auto& y = metadata.planes[0];
    if (metadata.width <= 1 || metadata.height <= 1 || y.byte_count <= 0 || bytes.empty()) return 0.0;
    const int step_x = std::max(1, metadata.width / 64);
    const int step_y = std::max(1, metadata.height / 64);
    long long total = 0;
    long long count = 0;
    for (int row = 0; row < metadata.height; row += step_y) {
        const int down_row = std::min(metadata.height - 1, row + step_y);
        for (int col = 0; col < metadata.width - step_x; col += step_x) {
            const uint8_t center = sample_burst_plane(bytes, 0, y, row, col, 16);
            const uint8_t right = sample_burst_plane(bytes, 0, y, row, col + step_x, center);
            const uint8_t down = sample_burst_plane(bytes, 0, y, down_row, col, center);
            total += std::abs(static_cast<int>(center) - static_cast<int>(right));
            total += std::abs(static_cast<int>(center) - static_cast<int>(down));
            count += 2;
        }
    }
    return count > 0 ? static_cast<double>(total) / static_cast<double>(count) : 0.0;
}

std::vector<uint8_t> convert_yuv_to_rgba(const std::vector<uint8_t>& bytes, const BurstMetadata& metadata) {
    std::vector<uint8_t> rgba(static_cast<size_t>(metadata.width) * static_cast<size_t>(metadata.height) * 4u);
    const int y_offset = 0;
    const int u_offset = metadata.planes[0].byte_count;
    const int v_offset = metadata.planes[0].byte_count + metadata.planes[1].byte_count;
    for (int row = 0; row < metadata.height; ++row) {
        for (int col = 0; col < metadata.width; ++col) {
            const int y_value = sample_burst_plane(bytes, y_offset, metadata.planes[0], row, col, 16);
            const int chroma_row = row / 2;
            const int chroma_col = col / 2;
            const int u_value = static_cast<int>(sample_burst_plane(bytes, u_offset, metadata.planes[1], chroma_row, chroma_col, 128)) - 128;
            const int v_value = static_cast<int>(sample_burst_plane(bytes, v_offset, metadata.planes[2], chroma_row, chroma_col, 128)) - 128;
            const int r = std::max(0, std::min(255, static_cast<int>(std::round(y_value + 1.402 * v_value))));
            const int g = std::max(0, std::min(255, static_cast<int>(std::round(y_value - 0.344136 * u_value - 0.714136 * v_value))));
            const int b = std::max(0, std::min(255, static_cast<int>(std::round(y_value + 1.772 * u_value))));
            const size_t out = (static_cast<size_t>(row) * static_cast<size_t>(metadata.width) + static_cast<size_t>(col)) * 4u;
            rgba[out + 0] = static_cast<uint8_t>(r);
            rgba[out + 1] = static_cast<uint8_t>(g);
            rgba[out + 2] = static_cast<uint8_t>(b);
            rgba[out + 3] = 255;
        }
    }
    return rgba;
}

template <typename RowFn>
void parallel_for_rows(int row_count, RowFn&& row_fn) {
    if (row_count <= 0) return;
    const unsigned hardware_threads = std::max(1u, std::thread::hardware_concurrency());
    const unsigned worker_count = std::min<unsigned>(
        std::min<unsigned>(hardware_threads, 8u),
        static_cast<unsigned>(std::max(1, row_count / 32))
    );
    if (worker_count <= 1) {
        for (int row = 0; row < row_count; ++row) row_fn(row);
        return;
    }
    std::vector<std::thread> workers;
    workers.reserve(worker_count);
    for (unsigned worker = 0; worker < worker_count; ++worker) {
        const int begin = static_cast<int>((static_cast<int64_t>(worker) * row_count) / worker_count);
        const int end = static_cast<int>((static_cast<int64_t>(worker + 1) * row_count) / worker_count);
        workers.emplace_back([begin, end, &row_fn]() {
            for (int row = begin; row < end; ++row) row_fn(row);
        });
    }
    for (auto& worker : workers) worker.join();
}

std::vector<uint8_t> downscale_rgba_nearest(
    const std::vector<uint8_t>& rgba,
    int width,
    int height,
    int out_width,
    int out_height
) {
    std::vector<uint8_t> out(static_cast<size_t>(out_width) * static_cast<size_t>(out_height) * 4u);
    parallel_for_rows(out_height, [&](int y) {
        const int src_y = std::min(height - 1, static_cast<int>((static_cast<int64_t>(y) * height) / std::max(1, out_height)));
        for (int x = 0; x < out_width; ++x) {
            const int src_x = std::min(width - 1, static_cast<int>((static_cast<int64_t>(x) * width) / std::max(1, out_width)));
            const size_t src = (static_cast<size_t>(src_y) * static_cast<size_t>(width) + static_cast<size_t>(src_x)) * 4u;
            const size_t dst = (static_cast<size_t>(y) * static_cast<size_t>(out_width) + static_cast<size_t>(x)) * 4u;
            out[dst + 0] = rgba[src + 0];
            out[dst + 1] = rgba[src + 1];
            out[dst + 2] = rgba[src + 2];
            out[dst + 3] = rgba[src + 3];
        }
    });
    return out;
}

std::vector<uint8_t> downscale_rgba_bilinear(
    const std::vector<uint8_t>& rgba,
    int width,
    int height,
    int out_width,
    int out_height
) {
    std::vector<uint8_t> out(static_cast<size_t>(out_width) * static_cast<size_t>(out_height) * 4u);
    if (width <= 0 || height <= 0 || out_width <= 0 || out_height <= 0 || rgba.empty()) return out;
    struct ScaleSample {
        int a = 0;
        int b = 0;
        int weight = 0;
    };
    constexpr int kScale = 256;
    std::vector<ScaleSample> x_samples(static_cast<size_t>(out_width));
    std::vector<ScaleSample> y_samples(static_cast<size_t>(out_height));
    for (int x = 0; x < out_width; ++x) {
        const int fixed = out_width > 1 ? (x * (width - 1) * kScale) / std::max(1, out_width - 1) : 0;
        const int x0 = std::max(0, std::min(width - 1, fixed / kScale));
        x_samples[static_cast<size_t>(x)] = {x0, std::min(width - 1, x0 + 1), fixed & (kScale - 1)};
    }
    for (int y = 0; y < out_height; ++y) {
        const int fixed = out_height > 1 ? (y * (height - 1) * kScale) / std::max(1, out_height - 1) : 0;
        const int y0 = std::max(0, std::min(height - 1, fixed / kScale));
        y_samples[static_cast<size_t>(y)] = {y0, std::min(height - 1, y0 + 1), fixed & (kScale - 1)};
    }
    parallel_for_rows(out_height, [&](int y) {
        const ScaleSample sy = y_samples[static_cast<size_t>(y)];
        for (int x = 0; x < out_width; ++x) {
            const ScaleSample sx = x_samples[static_cast<size_t>(x)];
            const size_t p00 = (static_cast<size_t>(sy.a) * static_cast<size_t>(width) + static_cast<size_t>(sx.a)) * 4u;
            const size_t p10 = (static_cast<size_t>(sy.a) * static_cast<size_t>(width) + static_cast<size_t>(sx.b)) * 4u;
            const size_t p01 = (static_cast<size_t>(sy.b) * static_cast<size_t>(width) + static_cast<size_t>(sx.a)) * 4u;
            const size_t p11 = (static_cast<size_t>(sy.b) * static_cast<size_t>(width) + static_cast<size_t>(sx.b)) * 4u;
            const size_t dst = (static_cast<size_t>(y) * static_cast<size_t>(out_width) + static_cast<size_t>(x)) * 4u;
            for (size_t ch = 0; ch < 4u; ++ch) {
                const int top = static_cast<int>(rgba[p00 + ch]) * (kScale - sx.weight) + static_cast<int>(rgba[p10 + ch]) * sx.weight;
                const int bottom = static_cast<int>(rgba[p01 + ch]) * (kScale - sx.weight) + static_cast<int>(rgba[p11 + ch]) * sx.weight;
                const int value = (top * (kScale - sy.weight) + bottom * sy.weight + (kScale * kScale / 2)) / (kScale * kScale);
                out[dst + ch] = static_cast<uint8_t>(std::max(0, std::min(255, value)));
            }
        }
    });
    return out;
}

std::string process_yuv_burst_native(
    const std::string& manifest_path,
    const std::string& output_rgba_path,
    const std::string& preview_rgba_path,
    int preview_max_edge
) {
    const std::string manifest = read_text_file(manifest_path);
    if (manifest.empty()) return processor_error_json("missing burst manifest");
    if (parse_string_key(manifest, "format") != "YUV_420_888") {
        return processor_error_json("unsupported RAW burst processing");
    }
    const auto frames = parse_burst_frames(manifest);
    if (frames.empty()) return processor_error_json("burst manifest has no frames");
    double best_score = -1.0;
    int best_index = -1;
    BurstFrameInfo best_frame;
    BurstMetadata best_metadata;
    std::vector<uint8_t> best_bytes;
    int rejected = 0;
    for (const auto& frame : frames) {
        const std::string metadata_json = read_text_file(frame.metadata_path);
        const BurstMetadata metadata = parse_burst_metadata(metadata_json);
        const auto bytes = read_binary_file(frame.frame_path);
        if (metadata.width <= 0 || metadata.height <= 0 || bytes.empty()) {
            rejected += 1;
            continue;
        }
        const double score = score_yuv_luma_sharpness(bytes, metadata);
        if (score > best_score) {
            best_score = score;
            best_index = frame.index;
            best_frame = frame;
            best_metadata = metadata;
            best_bytes = bytes;
        }
    }
    if (best_index < 0) return processor_error_json("burst manifest has no processable YUV frames");
    const auto rgba = convert_yuv_to_rgba(best_bytes, best_metadata);
    if (!write_binary_file(output_rgba_path, rgba)) {
        return processor_error_json("could not write full RGBA output");
    }
    int preview_width = 0;
    int preview_height = 0;
    if (preview_max_edge > 0 && !preview_rgba_path.empty()) {
        const int max_edge = std::max(1, preview_max_edge);
        const double scale = std::min(
            1.0,
            static_cast<double>(max_edge) / static_cast<double>(std::max(best_metadata.width, best_metadata.height))
        );
        preview_width = std::max(1, static_cast<int>(std::round(best_metadata.width * scale)));
        preview_height = std::max(1, static_cast<int>(std::round(best_metadata.height * scale)));
        const auto preview = downscale_rgba_nearest(rgba, best_metadata.width, best_metadata.height, preview_width, preview_height);
        if (!write_binary_file(preview_rgba_path, preview)) {
            return processor_error_json("could not write preview RGBA output");
        }
    }
    const int used = static_cast<int>(frames.size()) - rejected;
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"mode\":\"sharpest_native\","
        << "\"reference_frame\":" << best_index << ","
        << "\"used_frames\":" << used << ","
        << "\"rejected_frames\":" << rejected << ","
        << "\"width\":" << best_metadata.width << ","
        << "\"height\":" << best_metadata.height << ","
        << "\"preview_width\":" << preview_width << ","
        << "\"preview_height\":" << preview_height << ","
        << "\"score\":" << best_score << ","
        << "\"selected_frame_path\":\"" << json_escape(best_frame.frame_path) << "\"}";
    return out.str();
}

std::vector<double> parse_number_array_key(const std::string& json, const std::string& key) {
    std::vector<double> out;
    const auto key_pos = json.find("\"" + key + "\"");
    if (key_pos == std::string::npos) return out;
    const auto open = json.find('[', key_pos);
    const auto close = open == std::string::npos ? std::string::npos : json.find(']', open);
    if (open == std::string::npos || close == std::string::npos || close <= open) return out;
    std::string::size_type pos = open + 1;
    while (pos < close) {
        auto value = number_after(json, pos);
        if (!value.has_value()) break;
        out.push_back(value.value());
        const auto comma = json.find(',', pos);
        if (comma == std::string::npos || comma >= close) break;
        pos = comma + 1;
    }
    return out;
}

struct RawFrameData {
    int index = 0;
    int width = 0;
    int height = 0;
    int row_stride = 0;
    int pixel_stride = 2;
    int white_level = 65535;
    std::string cfa = "UNKNOWN";
    std::array<double, 4> black = {0.0, 0.0, 0.0, 0.0};
    std::array<double, 4> gains = {1.0, 1.0, 1.0, 1.0};
    std::array<double, 9> transform = {1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0};
    bool gains_usable = false;
    bool transform_usable = false;
    bool lens_shading_usable = false;
    int lens_shading_cols = 0;
    int lens_shading_rows = 0;
    std::vector<float> lens_shading_values;
    std::string raw16_path;
    double sharpness_score = -1.0;
    int sensor_sensitivity_iso = 0;
    int64_t sensor_exposure_time_ns = 0;
    int64_t sensor_frame_duration_ns = 0;
    std::vector<uint8_t> bytes;
    std::shared_ptr<struct MappedRawFile> mapped_bytes;
};

struct MappedRawFile {
    int fd = -1;
    void* data = nullptr;
    size_t size = 0;

    MappedRawFile() = default;
    MappedRawFile(const MappedRawFile&) = delete;
    MappedRawFile& operator=(const MappedRawFile&) = delete;

    ~MappedRawFile() {
        if (data != nullptr && size > 0) {
            munmap(data, size);
        }
        if (fd >= 0) {
            close(fd);
        }
    }
};

enum class RawCfaPattern {
    Rggb,
    Grbg,
    Gbrg,
    Bggr,
    Unknown,
};

struct ReducedBayerFrame {
    int width = 0;
    int height = 0;
    RawCfaPattern pattern = RawCfaPattern::Unknown;
    std::array<double, 4> gains = {1.0, 1.0, 1.0, 1.0};
    std::array<double, 9> transform = {1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0};
    bool gains_usable = false;
    bool transform_usable = false;
    bool lens_shading_usable = false;
    std::vector<float> values;
};

struct IntSpan {
    int begin = 0;
    int end = 0;
};

struct RawNormalizeTable {
    std::array<float, 4> black = {0.0f, 0.0f, 0.0f, 0.0f};
    std::array<float, 4> scale = {1.0f, 1.0f, 1.0f, 1.0f};
};

struct AlignmentOffset {
    int index = 0;
    int dx = 0;
    int dy = 0;
    double score = 0.0;
    bool accepted = true;
};

struct TileAlignmentOffset {
    int frame_index = 0;
    int tile_x = 0;
    int tile_y = 0;
    int dx = 0;
    int dy = 0;
    double score = 0.0;
    bool accepted = true;
};

struct TileAlignmentSmoothingResult {
    int changed_offsets = 0;
};

struct SampledTileOffset {
    int dx = 0;
    int dy = 0;
    bool accepted = false;
};

struct RawMergeTiming {
    double reduce_ms = 0.0;
    double align_ms = 0.0;
    double merge_ms = 0.0;
};

struct RawMotionMergeTelemetry {
    int64_t rejected_samples = 0;
    int64_t raw_rejected_samples = 0;
    int64_t total_samples = 0;
};

struct RenderStyleProfile {
    const char* name = "Neutral";
    float saturation = 1.0f;
    float contrast = 1.0f;
    float red_bias = 1.0f;
    float blue_bias = 1.0f;
    float target_p95 = 0.85f;
    float highlight_rolloff = 0.35f;
    float shadow_lift = 0.0f;
    float exposure_bias = 1.0f;
    float local_contrast = 0.0f;
    float sharpening = 0.0f;
    float chroma_denoise = 0.0f;
};

struct RawToneMapTelemetry {
    double exposure = 1.0;
    double p50 = 0.0;
    double p95 = 0.0;
    double p99 = 0.0;
    double highlight_rolloff = 0.35;
    double shadow_lift = 0.0;
};

struct RawArtifactTelemetry {
    int64_t inspected_pixels = 0;
    int64_t purple_pixels_before = 0;
    int64_t purple_pixels_after = 0;
    int64_t purple_suppressed_pixels = 0;
};

struct RawNeutralCastTelemetry {
    int64_t neutral_samples = 0;
    double red_gain = 1.0;
    double green_gain = 1.0;
    double blue_gain = 1.0;
    bool applied = false;
};

struct RawRenderResult {
    std::vector<uint8_t> rgba;
    RawToneMapTelemetry tone;
    RawArtifactTelemetry artifacts;
    RawNeutralCastTelemetry neutral_cast;
};

double raw_shadow_purple_ratio_after(const RawArtifactTelemetry& artifacts) {
    return artifacts.inspected_pixels > 0
        ? static_cast<double>(artifacts.purple_pixels_after) / static_cast<double>(artifacts.inspected_pixels)
        : 0.0;
}

std::string raw_quality_verdict_for_artifacts(const RawArtifactTelemetry& artifacts) {
    const double ratio = raw_shadow_purple_ratio_after(artifacts);
    if (ratio >= 0.05) return "artifact_fail";
    if (ratio >= 0.025) return "artifact_warn";
    return "ok";
}

double elapsed_ms(std::chrono::steady_clock::time_point start, std::chrono::steady_clock::time_point end) {
    return std::chrono::duration<double, std::milli>(end - start).count();
}

std::string raw_processor_error_json(const std::string& message) {
    return "{\"status\":\"error\",\"mode\":\"raw_single_frame\",\"error\":\"" + json_escape(message) + "\"}";
}

std::shared_ptr<MappedRawFile> map_raw_file(const std::string& path) {
    int fd = open(path.c_str(), O_RDONLY);
    if (fd < 0) return nullptr;
    struct stat st {};
    if (fstat(fd, &st) != 0 || st.st_size <= 0) {
        close(fd);
        return nullptr;
    }
    void* data = mmap(nullptr, static_cast<size_t>(st.st_size), PROT_READ, MAP_PRIVATE, fd, 0);
    if (data == MAP_FAILED) {
        close(fd);
        return nullptr;
    }
    auto mapped = std::make_shared<MappedRawFile>();
    mapped->fd = fd;
    mapped->data = data;
    mapped->size = static_cast<size_t>(st.st_size);
    return mapped;
}

void load_raw_frame_bytes(RawFrameData& frame, bool prefer_mmap) {
    frame.bytes.clear();
    frame.mapped_bytes.reset();
    if (frame.raw16_path.empty()) return;
    if (prefer_mmap) {
        frame.mapped_bytes = map_raw_file(frame.raw16_path);
        if (frame.mapped_bytes != nullptr) return;
    }
    frame.bytes = read_binary_file(frame.raw16_path);
}

const uint8_t* raw_frame_byte_data(const RawFrameData& frame) {
    if (frame.mapped_bytes != nullptr && frame.mapped_bytes->data != nullptr) {
        return static_cast<const uint8_t*>(frame.mapped_bytes->data);
    }
    return frame.bytes.empty() ? nullptr : frame.bytes.data();
}

size_t raw_frame_byte_size(const RawFrameData& frame) {
    if (frame.mapped_bytes != nullptr && frame.mapped_bytes->data != nullptr) {
        return frame.mapped_bytes->size;
    }
    return frame.bytes.size();
}

bool raw_frame_has_bytes(const RawFrameData& frame) {
    return raw_frame_byte_data(frame) != nullptr && raw_frame_byte_size(frame) > 0;
}

const char* raw_frame_load_mode(const RawFrameData& frame) {
    return frame.mapped_bytes != nullptr ? "mmap" : "read";
}

bool raw_color_gains_usable(const std::array<double, 4>& gains) {
    for (double value : gains) {
        if (!std::isfinite(value) || value <= 0.0 || value > 16.0) return false;
    }
    return true;
}

bool raw_color_transform_usable(const std::array<double, 9>& transform) {
    double total_abs = 0.0;
    for (double value : transform) {
        if (!std::isfinite(value) || std::abs(value) > 8.0) return false;
        total_abs += std::abs(value);
    }
    return total_abs > 0.001;
}

std::array<double, 4> normalize_raw_color_gains(const std::array<double, 4>& gains, bool usable) {
    if (!usable) return {1.0, 1.0, 1.0, 1.0};
    const double green = std::max(0.001, (gains[1] + gains[2]) * 0.5);
    return {
        std::max(0.55, std::min(2.60, gains[0] / green)),
        1.0,
        1.0,
        std::max(0.55, std::min(2.60, gains[3] / green)),
    };
}

std::array<double, 9> normalize_raw_color_transform(const std::array<double, 9>& transform, bool usable) {
    if (!usable) return {1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0};
    std::array<double, 9> out = transform;
    for (int row = 0; row < 3; ++row) {
        const size_t base = static_cast<size_t>(row) * 3u;
        const double row_sum = out[base + 0] + out[base + 1] + out[base + 2];
        if (std::abs(row_sum) > 0.001 && std::isfinite(row_sum)) {
            out[base + 0] /= row_sum;
            out[base + 1] /= row_sum;
            out[base + 2] /= row_sum;
        }
    }
    return out;
}

RawFrameData parse_raw_frame_data(const BurstFrameInfo& frame, bool load_bytes = true) {
    RawFrameData out;
    out.index = frame.index;
    const std::string metadata_json = read_text_file(frame.metadata_path);
    out.raw16_path = parse_string_key(metadata_json, "raw16_path");
    out.width = static_cast<int>(parse_number_key(metadata_json, "width", 0.0));
    out.height = static_cast<int>(parse_number_key(metadata_json, "height", 0.0));
    out.row_stride = static_cast<int>(parse_number_key(metadata_json, "row_stride", 0.0));
    out.pixel_stride = static_cast<int>(parse_number_key(metadata_json, "pixel_stride", 2.0));
    out.white_level = static_cast<int>(parse_number_key(metadata_json, "white_level", 65535.0));
    out.sharpness_score = parse_number_key(metadata_json, "raw_sharpness_score", -1.0);
    out.sensor_sensitivity_iso = static_cast<int>(parse_number_key(metadata_json, "sensor_sensitivity_iso", 0.0));
    out.sensor_exposure_time_ns = static_cast<int64_t>(parse_number_key(metadata_json, "sensor_exposure_time_ns", 0.0));
    out.sensor_frame_duration_ns = static_cast<int64_t>(parse_number_key(metadata_json, "sensor_frame_duration_ns", 0.0));
    out.cfa = parse_string_key(metadata_json, "color_filter_arrangement");
    const auto black = parse_number_array_key(metadata_json, "black_level_pattern");
    for (size_t i = 0; i < black.size() && i < out.black.size(); ++i) out.black[i] = black[i];
    const auto gains = parse_number_array_key(metadata_json, "color_correction_gains");
    for (size_t i = 0; i < gains.size() && i < out.gains.size(); ++i) out.gains[i] = gains[i];
    out.gains_usable = gains.size() >= out.gains.size() && raw_color_gains_usable(out.gains);
    out.gains = normalize_raw_color_gains(out.gains, out.gains_usable);
    const auto transform = parse_number_array_key(metadata_json, "color_correction_transform");
    for (size_t i = 0; i < transform.size() && i < out.transform.size(); ++i) out.transform[i] = transform[i];
    out.transform_usable = transform.size() >= out.transform.size() && raw_color_transform_usable(out.transform);
    out.transform = normalize_raw_color_transform(out.transform, out.transform_usable);
    out.lens_shading_cols = static_cast<int>(parse_number_key(metadata_json, "columns", 0.0));
    out.lens_shading_rows = static_cast<int>(parse_number_key(metadata_json, "rows", 0.0));
    const auto lens_values = parse_number_array_key(metadata_json, "values");
    if (out.lens_shading_cols > 1 && out.lens_shading_rows > 1
        && lens_values.size() >= static_cast<size_t>(out.lens_shading_cols) * static_cast<size_t>(out.lens_shading_rows) * 4u) {
        out.lens_shading_values.reserve(lens_values.size());
        for (double value : lens_values) {
            out.lens_shading_values.push_back(static_cast<float>(std::max(0.25, std::min(8.0, value))));
        }
        out.lens_shading_usable = true;
    }
    if (load_bytes) {
        load_raw_frame_bytes(out, false);
    }
    if (out.row_stride <= 0) out.row_stride = out.width * std::max(1, out.pixel_stride);
    return out;
}

char raw_color_at(const std::string& cfa, int row, int col) {
    const bool even_row = (row & 1) == 0;
    const bool even_col = (col & 1) == 0;
    if (cfa == "RGGB") return even_row ? (even_col ? 'R' : 'G') : (even_col ? 'G' : 'B');
    if (cfa == "GRBG") return even_row ? (even_col ? 'G' : 'R') : (even_col ? 'B' : 'G');
    if (cfa == "GBRG") return even_row ? (even_col ? 'G' : 'B') : (even_col ? 'R' : 'G');
    if (cfa == "BGGR") return even_row ? (even_col ? 'B' : 'G') : (even_col ? 'G' : 'R');
    return '?';
}

RawCfaPattern parse_raw_cfa_pattern(const std::string& cfa) {
    if (cfa == "RGGB") return RawCfaPattern::Rggb;
    if (cfa == "GRBG") return RawCfaPattern::Grbg;
    if (cfa == "GBRG") return RawCfaPattern::Gbrg;
    if (cfa == "BGGR") return RawCfaPattern::Bggr;
    return RawCfaPattern::Unknown;
}

char raw_color_at_pattern(RawCfaPattern pattern, int row, int col) {
    const bool even_row = (row & 1) == 0;
    const bool even_col = (col & 1) == 0;
    switch (pattern) {
        case RawCfaPattern::Rggb:
            return even_row ? (even_col ? 'R' : 'G') : (even_col ? 'G' : 'B');
        case RawCfaPattern::Grbg:
            return even_row ? (even_col ? 'G' : 'R') : (even_col ? 'B' : 'G');
        case RawCfaPattern::Gbrg:
            return even_row ? (even_col ? 'G' : 'B') : (even_col ? 'R' : 'G');
        case RawCfaPattern::Bggr:
            return even_row ? (even_col ? 'B' : 'G') : (even_col ? 'G' : 'R');
        default:
            return '?';
    }
}

uint16_t raw16_value_at(const RawFrameData& frame, int row, int col) {
    const int idx = row * frame.row_stride + col * frame.pixel_stride;
    const uint8_t* bytes = raw_frame_byte_data(frame);
    if (bytes == nullptr || idx < 0 || static_cast<size_t>(idx + 1) >= raw_frame_byte_size(frame)) return 0;
    return static_cast<uint16_t>(bytes[static_cast<size_t>(idx)] | (bytes[static_cast<size_t>(idx + 1)] << 8));
}

inline uint16_t raw16_value_at_unchecked(const RawFrameData& frame, int row, int col) {
    const size_t idx = static_cast<size_t>(row * frame.row_stride + col * frame.pixel_stride);
    const uint8_t* bytes = raw_frame_byte_data(frame);
    return static_cast<uint16_t>(bytes[idx] | (bytes[idx + 1] << 8));
}

double normalized_raw_at(const RawFrameData& frame, int row, int col) {
    row = std::max(0, std::min(frame.height - 1, row));
    col = std::max(0, std::min(frame.width - 1, col));
    const int black_index = ((row & 1) * 2) + (col & 1);
    const double black = frame.black[static_cast<size_t>(black_index)];
    const double white = std::max(black + 1.0, static_cast<double>(frame.white_level));
    const double value = static_cast<double>(raw16_value_at(frame, row, col));
    return std::max(0.0, std::min(1.0, (value - black) / (white - black)));
}

double raw_channel_average(const RawFrameData& frame, int row, int col, char wanted) {
    double total = 0.0;
    int count = 0;
    for (int dy = -2; dy <= 2; ++dy) {
        for (int dx = -2; dx <= 2; ++dx) {
            const int yy = std::max(0, std::min(frame.height - 1, row + dy));
            const int xx = std::max(0, std::min(frame.width - 1, col + dx));
            if (raw_color_at(frame.cfa, yy, xx) == wanted) {
                total += normalized_raw_at(frame, yy, xx);
                count += 1;
            }
        }
    }
    return count > 0 ? total / static_cast<double>(count) : normalized_raw_at(frame, row, col);
}

inline double normalized_raw_at_clamped(const RawFrameData& frame, int row, int col) {
    row = row < 0 ? 0 : (row >= frame.height ? frame.height - 1 : row);
    col = col < 0 ? 0 : (col >= frame.width ? frame.width - 1 : col);
    const int black_index = ((row & 1) << 1) | (col & 1);
    const double black = frame.black[static_cast<size_t>(black_index)];
    const double white = std::max(black + 1.0, static_cast<double>(frame.white_level));
    const double value = static_cast<double>(raw16_value_at(frame, row, col));
    const double normalized = (value - black) / (white - black);
    return normalized < 0.0 ? 0.0 : (normalized > 1.0 ? 1.0 : normalized);
}

inline double normalized_raw_at_unchecked(const RawFrameData& frame, int row, int col) {
    const int black_index = ((row & 1) << 1) | (col & 1);
    const double black = frame.black[static_cast<size_t>(black_index)];
    const double white = std::max(black + 1.0, static_cast<double>(frame.white_level));
    const double normalized = (static_cast<double>(raw16_value_at_unchecked(frame, row, col)) - black) / (white - black);
    return normalized < 0.0 ? 0.0 : (normalized > 1.0 ? 1.0 : normalized);
}

RawNormalizeTable raw_normalize_table(const RawFrameData& frame) {
    RawNormalizeTable table;
    for (size_t i = 0; i < table.black.size(); ++i) {
        const float black = static_cast<float>(frame.black[i]);
        const float white = std::max(black + 1.0f, static_cast<float>(frame.white_level));
        table.black[i] = black;
        table.scale[i] = 1.0f / (white - black);
    }
    return table;
}

inline int raw_lens_shading_channel_index(const RawFrameData& frame, int row, int col) {
    const char color = raw_color_at(frame.cfa, row, col);
    if (color == 'R') return 0;
    if (color == 'B') return 3;
    return (row & 1) == 0 ? 1 : 2;
}

inline float raw_lens_shading_gain_at(const RawFrameData& frame, int row, int col) {
    if (!frame.lens_shading_usable || frame.lens_shading_cols <= 1 || frame.lens_shading_rows <= 1) return 1.0f;
    const int channel = raw_lens_shading_channel_index(frame, row, col);
    const double gx = (static_cast<double>(col) / static_cast<double>(std::max(1, frame.width - 1)))
        * static_cast<double>(frame.lens_shading_cols - 1);
    const double gy = (static_cast<double>(row) / static_cast<double>(std::max(1, frame.height - 1)))
        * static_cast<double>(frame.lens_shading_rows - 1);
    const int x0 = std::max(0, std::min(frame.lens_shading_cols - 1, static_cast<int>(std::floor(gx))));
    const int y0 = std::max(0, std::min(frame.lens_shading_rows - 1, static_cast<int>(std::floor(gy))));
    const int x1 = std::max(0, std::min(frame.lens_shading_cols - 1, x0 + 1));
    const int y1 = std::max(0, std::min(frame.lens_shading_rows - 1, y0 + 1));
    const float wx = static_cast<float>(std::max(0.0, std::min(1.0, gx - static_cast<double>(x0))));
    const float wy = static_cast<float>(std::max(0.0, std::min(1.0, gy - static_cast<double>(y0))));
    auto at = [&](int x, int y) {
        const size_t idx = ((static_cast<size_t>(y) * static_cast<size_t>(frame.lens_shading_cols) + static_cast<size_t>(x)) * 4u)
            + static_cast<size_t>(channel);
        if (idx >= frame.lens_shading_values.size()) return 1.0f;
        return frame.lens_shading_values[idx];
    };
    const float top = at(x0, y0) * (1.0f - wx) + at(x1, y0) * wx;
    const float bottom = at(x0, y1) * (1.0f - wx) + at(x1, y1) * wx;
    const float gain = top * (1.0f - wy) + bottom * wy;
    return std::max(0.25f, std::min(4.0f, gain));
}

inline float normalized_raw_at_unchecked_fast(
    const RawFrameData& frame,
    const RawNormalizeTable& table,
    int row,
    int col
) {
    const int black_index = ((row & 1) << 1) | (col & 1);
    const float normalized = (static_cast<float>(raw16_value_at_unchecked(frame, row, col)) - table.black[static_cast<size_t>(black_index)])
        * table.scale[static_cast<size_t>(black_index)];
    const float shaded = normalized * raw_lens_shading_gain_at(frame, row, col);
    return shaded < 0.0f ? 0.0f : (shaded > 1.0f ? 1.0f : shaded);
}

inline double raw_channel_average_fast(
    const RawFrameData& frame,
    RawCfaPattern pattern,
    int row,
    int col,
    char wanted
) {
    double total = 0.0;
    int count = 0;
    for (int dy = -1; dy <= 1; ++dy) {
        const int yy = row + dy;
        for (int dx = -1; dx <= 1; ++dx) {
            const int xx = col + dx;
            if (raw_color_at_pattern(pattern, yy, xx) == wanted) {
                total += normalized_raw_at_clamped(frame, yy, xx);
                count += 1;
            }
        }
    }
    return count > 0 ? total / static_cast<double>(count) : normalized_raw_at_clamped(frame, row, col);
}

inline double raw_green_proxy_fast(const RawFrameData& frame, RawCfaPattern pattern, int row, int col) {
    if (raw_color_at_pattern(pattern, row, col) == 'G') {
        return normalized_raw_at_clamped(frame, row, col);
    }
    double total = 0.0;
    int count = 0;
    if (raw_color_at_pattern(pattern, row, col - 1) == 'G') {
        total += normalized_raw_at_clamped(frame, row, col - 1);
        count += 1;
    }
    if (raw_color_at_pattern(pattern, row, col + 1) == 'G') {
        total += normalized_raw_at_clamped(frame, row, col + 1);
        count += 1;
    }
    if (raw_color_at_pattern(pattern, row - 1, col) == 'G') {
        total += normalized_raw_at_clamped(frame, row - 1, col);
        count += 1;
    }
    if (raw_color_at_pattern(pattern, row + 1, col) == 'G') {
        total += normalized_raw_at_clamped(frame, row + 1, col);
        count += 1;
    }
    return count > 0 ? total / static_cast<double>(count) : normalized_raw_at_clamped(frame, row, col);
}

inline float reduced_bayer_value_at_clamped(const ReducedBayerFrame& frame, int row, int col) {
    row = row < 0 ? 0 : (row >= frame.height ? frame.height - 1 : row);
    col = col < 0 ? 0 : (col >= frame.width ? frame.width - 1 : col);
    return frame.values[static_cast<size_t>(row) * static_cast<size_t>(frame.width) + static_cast<size_t>(col)];
}

inline float reduced_bayer_value_at_unchecked(const ReducedBayerFrame& frame, int row, int col) {
    return frame.values[static_cast<size_t>(row) * static_cast<size_t>(frame.width) + static_cast<size_t>(col)];
}

inline double reduced_channel_average_fast(
    const ReducedBayerFrame& frame,
    int row,
    int col,
    char wanted
) {
    double total = 0.0;
    int count = 0;
    for (int dy = -1; dy <= 1; ++dy) {
        const int yy = row + dy;
        for (int dx = -1; dx <= 1; ++dx) {
            const int xx = col + dx;
            if (raw_color_at_pattern(frame.pattern, yy, xx) == wanted) {
                total += reduced_bayer_value_at_clamped(frame, yy, xx);
                count += 1;
            }
        }
    }
    return count > 0 ? total / static_cast<double>(count) : reduced_bayer_value_at_clamped(frame, row, col);
}

double score_raw_green_sharpness(const RawFrameData& frame) {
    if (frame.width <= 1 || frame.height <= 1 || !raw_frame_has_bytes(frame)) return -1.0;
    const RawCfaPattern pattern = parse_raw_cfa_pattern(frame.cfa);
    const int step_x = std::max(1, frame.width / 64);
    const int step_y = std::max(1, frame.height / 64);
    double total = 0.0;
    int count = 0;
    for (int row = 0; row < frame.height - step_y; row += step_y) {
        for (int col = 0; col < frame.width - step_x; col += step_x) {
            const double center = raw_green_proxy_fast(frame, pattern, row, col);
            total += std::abs(center - raw_green_proxy_fast(frame, pattern, row, col + step_x));
            total += std::abs(center - raw_green_proxy_fast(frame, pattern, row + step_y, col));
            count += 2;
        }
    }
    return count > 0 ? total / static_cast<double>(count) : 0.0;
}

double raw_exposure_product(const RawFrameData& frame) {
    if (frame.sensor_sensitivity_iso <= 0 || frame.sensor_exposure_time_ns <= 0) return 0.0;
    return static_cast<double>(frame.sensor_sensitivity_iso) * static_cast<double>(frame.sensor_exposure_time_ns);
}

bool raw_exposure_compatible(const RawFrameData& reference, const RawFrameData& candidate) {
    const double reference_ev = raw_exposure_product(reference);
    const double candidate_ev = raw_exposure_product(candidate);
    if (reference_ev <= 0.0 || candidate_ev <= 0.0) return true;
    const double ratio = candidate_ev / reference_ev;
    return ratio >= 0.92 && ratio <= 1.08;
}

bool raw_sharpness_compatible(double best_score, const RawFrameData& candidate) {
    if (best_score <= 0.0 || candidate.sharpness_score < 0.0) return true;
    return candidate.sharpness_score >= best_score * 0.55;
}

ReducedBayerFrame downsample_raw_bayer_area(const RawFrameData& frame, int out_width, int out_height) {
    ReducedBayerFrame out;
    out.width = out_width;
    out.height = out_height;
    out.pattern = parse_raw_cfa_pattern(frame.cfa);
    out.gains = frame.gains;
    out.transform = frame.transform;
    out.gains_usable = frame.gains_usable;
    out.transform_usable = frame.transform_usable;
    out.lens_shading_usable = frame.lens_shading_usable;
    out.values.resize(static_cast<size_t>(out_width) * static_cast<size_t>(out_height));
    const RawNormalizeTable normalize = raw_normalize_table(frame);
    std::vector<IntSpan> row_spans(static_cast<size_t>(out_height));
    std::vector<IntSpan> col_spans(static_cast<size_t>(out_width));
    for (int row = 0; row < out_height; ++row) {
        int y0 = static_cast<int>((static_cast<int64_t>(row) * frame.height) / std::max(1, out_height));
        int y1 = static_cast<int>((static_cast<int64_t>(row + 1) * frame.height) / std::max(1, out_height));
        row_spans[static_cast<size_t>(row)] = {
            std::max(0, std::min(frame.height - 1, y0)),
            0,
        };
        row_spans[static_cast<size_t>(row)].end =
            std::max(row_spans[static_cast<size_t>(row)].begin + 1, std::min(frame.height, y1));
    }
    for (int col = 0; col < out_width; ++col) {
        int x0 = static_cast<int>((static_cast<int64_t>(col) * frame.width) / std::max(1, out_width));
        int x1 = static_cast<int>((static_cast<int64_t>(col + 1) * frame.width) / std::max(1, out_width));
        col_spans[static_cast<size_t>(col)] = {
            std::max(0, std::min(frame.width - 1, x0)),
            0,
        };
        col_spans[static_cast<size_t>(col)].end =
            std::max(col_spans[static_cast<size_t>(col)].begin + 1, std::min(frame.width, x1));
    }
    parallel_for_rows(out_height, [&](int row) {
        const IntSpan y = row_spans[static_cast<size_t>(row)];
        for (int col = 0; col < out_width; ++col) {
            const IntSpan x = col_spans[static_cast<size_t>(col)];
            // Match the output Bayer site parity directly. This avoids a per-source-pixel
            // CFA branch in the hottest RAW reduction loop.
            int yy0 = y.begin;
            if (((yy0 ^ row) & 1) != 0) yy0 += 1;
            int xx0 = x.begin;
            if (((xx0 ^ col) & 1) != 0) xx0 += 1;
            float total = 0.0f;
            int count = 0;
            for (int yy = yy0; yy < y.end; yy += 2) {
                for (int xx = xx0; xx < x.end; xx += 2) {
                    total += normalized_raw_at_unchecked_fast(frame, normalize, yy, xx);
                    count += 1;
                }
            }
            if (count == 0) {
                const int center_y = std::min(frame.height - 1, (y.begin + y.end) / 2);
                const int center_x = std::min(frame.width - 1, (x.begin + x.end) / 2);
                total = normalized_raw_at_clamped(frame, center_y, center_x);
                count = 1;
            }
            out.values[static_cast<size_t>(row) * static_cast<size_t>(out_width) + static_cast<size_t>(col)] =
                total / static_cast<float>(count);
        }
    });
    return out;
}

ReducedBayerFrame average_reduced_bayer_frames(
    const std::vector<RawFrameData>& frames,
    int out_width,
    int out_height,
    RawMergeTiming* timing = nullptr
) {
    const auto reduce_start = std::chrono::steady_clock::now();
    ReducedBayerFrame out;
    if (frames.empty()) return out;
    out.width = out_width;
    out.height = out_height;
    out.pattern = parse_raw_cfa_pattern(frames.front().cfa);
    out.gains = frames.front().gains;
    out.transform = frames.front().transform;
    out.gains_usable = frames.front().gains_usable;
    out.transform_usable = frames.front().transform_usable;
    out.lens_shading_usable = frames.front().lens_shading_usable;
    out.values.assign(static_cast<size_t>(out_width) * static_cast<size_t>(out_height), 0.0f);
    for (const auto& frame : frames) {
        const auto reduced = downsample_raw_bayer_area(frame, out_width, out_height);
        for (size_t i = 0; i < out.values.size() && i < reduced.values.size(); ++i) {
            out.values[i] += reduced.values[i];
        }
    }
    const auto reduce_done = std::chrono::steady_clock::now();
    const auto merge_start = reduce_done;
    const float scale = 1.0f / static_cast<float>(std::max<size_t>(1, frames.size()));
    parallel_for_rows(out_height, [&](int row) {
        const size_t start = static_cast<size_t>(row) * static_cast<size_t>(out_width);
        for (int col = 0; col < out_width; ++col) {
            out.values[start + static_cast<size_t>(col)] *= scale;
        }
    });
    const auto merge_done = std::chrono::steady_clock::now();
    if (timing != nullptr) {
        timing->reduce_ms += elapsed_ms(reduce_start, reduce_done);
        timing->merge_ms += elapsed_ms(merge_start, merge_done);
    }
    return out;
}

double reduced_alignment_score(const ReducedBayerFrame& reference, const ReducedBayerFrame& candidate, int dx, int dy) {
    // green_alignment_proxy: Bayer-value proxy on the already reduced RAW plane.
    const int step_x = std::max(8, reference.width / 96);
    const int step_y = std::max(8, reference.height / 96);
    double total = 0.0;
    int count = 0;
    for (int row = step_y; row < reference.height - step_y; row += step_y) {
        const int cy = row + dy;
        if (cy < 0 || cy >= candidate.height) continue;
        for (int col = step_x; col < reference.width - step_x; col += step_x) {
            const int cx = col + dx;
            if (cx < 0 || cx >= candidate.width) continue;
            const float a = reduced_bayer_value_at_unchecked(reference, row, col);
            const float b = reduced_bayer_value_at_unchecked(candidate, cy, cx);
            total += std::abs(static_cast<double>(a) - static_cast<double>(b));
            count += 1;
        }
    }
    return count > 0 ? total / static_cast<double>(count) : std::numeric_limits<double>::infinity();
}

AlignmentOffset find_reduced_alignment_offset(const ReducedBayerFrame& reference, const ReducedBayerFrame& candidate, int index) {
    AlignmentOffset best;
    best.index = index;
    best.score = std::numeric_limits<double>::infinity();
    constexpr int kSearchRadius = 10;
    constexpr int kSearchStep = 2;
    for (int dy = -kSearchRadius; dy <= kSearchRadius; dy += kSearchStep) {
        for (int dx = -kSearchRadius; dx <= kSearchRadius; dx += kSearchStep) {
            const double score = reduced_alignment_score(reference, candidate, dx, dy);
            if (score < best.score) {
                best.dx = dx;
                best.dy = dy;
                best.score = score;
            }
        }
    }
    best.accepted = std::isfinite(best.score) && best.score < 0.08;
    return best;
}

double reduced_tile_alignment_score(
    const ReducedBayerFrame& reference,
    const ReducedBayerFrame& candidate,
    int x0,
    int y0,
    int x1,
    int y1,
    int dx,
    int dy
) {
    const int tile_width = std::max(1, x1 - x0);
    const int tile_height = std::max(1, y1 - y0);
    const int step_x = std::max(4, tile_width / 12);
    const int step_y = std::max(4, tile_height / 12);
    double total = 0.0;
    int count = 0;
    for (int row = y0 + step_y / 2; row < y1; row += step_y) {
        const int cy = row + dy;
        if (cy < 0 || cy >= candidate.height) continue;
        for (int col = x0 + step_x / 2; col < x1; col += step_x) {
            const int cx = col + dx;
            if (cx < 0 || cx >= candidate.width) continue;
            const float a = reduced_bayer_value_at_unchecked(reference, row, col);
            const float b = reduced_bayer_value_at_unchecked(candidate, cy, cx);
            total += std::abs(static_cast<double>(a) - static_cast<double>(b));
            count += 1;
        }
    }
    return count > 0 ? total / static_cast<double>(count) : std::numeric_limits<double>::infinity();
}

TileAlignmentOffset find_reduced_tile_alignment_offset(
    const ReducedBayerFrame& reference,
    const ReducedBayerFrame& candidate,
    int frame_index,
    int tile_x,
    int tile_y,
    int tile_cols,
    int tile_rows,
    const AlignmentOffset& global_offset
) {
    const int x0 = std::max(0, (tile_x * reference.width) / std::max(1, tile_cols));
    const int y0 = std::max(0, (tile_y * reference.height) / std::max(1, tile_rows));
    const int x1 = std::min(reference.width, ((tile_x + 1) * reference.width) / std::max(1, tile_cols));
    const int y1 = std::min(reference.height, ((tile_y + 1) * reference.height) / std::max(1, tile_rows));
    TileAlignmentOffset best;
    best.frame_index = frame_index;
    best.tile_x = tile_x;
    best.tile_y = tile_y;
    best.dx = global_offset.dx;
    best.dy = global_offset.dy;
    best.score = reduced_tile_alignment_score(reference, candidate, x0, y0, x1, y1, best.dx, best.dy);
    constexpr int kTileSearchRadius = 6;
    constexpr int kTileSearchStep = 2;
    for (int dy = global_offset.dy - kTileSearchRadius; dy <= global_offset.dy + kTileSearchRadius; dy += kTileSearchStep) {
        for (int dx = global_offset.dx - kTileSearchRadius; dx <= global_offset.dx + kTileSearchRadius; dx += kTileSearchStep) {
            const double score = reduced_tile_alignment_score(reference, candidate, x0, y0, x1, y1, dx, dy);
            if (score < best.score) {
                best.dx = dx;
                best.dy = dy;
                best.score = score;
            }
        }
    }
    best.accepted = global_offset.accepted && std::isfinite(best.score) && best.score < 0.035;
    return best;
}

TileAlignmentSmoothingResult smooth_tile_alignment_offsets_median_3x3(
    std::vector<TileAlignmentOffset>& offsets,
    size_t frame_count,
    int tile_cols,
    int tile_rows
) {
    TileAlignmentSmoothingResult result;
    if (frame_count <= 1 || tile_cols <= 0 || tile_rows <= 0) return result;
    const auto before = offsets;
    auto tile_index = [tile_cols, tile_rows](size_t frame, int tile_x, int tile_y) {
        return (frame * static_cast<size_t>(tile_rows) + static_cast<size_t>(tile_y))
            * static_cast<size_t>(tile_cols) + static_cast<size_t>(tile_x);
    };
    for (size_t frame = 1; frame < frame_count; ++frame) {
        for (int tile_y = 0; tile_y < tile_rows; ++tile_y) {
            for (int tile_x = 0; tile_x < tile_cols; ++tile_x) {
                const size_t idx = tile_index(frame, tile_x, tile_y);
                if (idx >= before.size() || !before[idx].accepted) continue;
                std::vector<int> neighbor_dx;
                std::vector<int> neighbor_dy;
                neighbor_dx.reserve(9);
                neighbor_dy.reserve(9);
                for (int oy = -1; oy <= 1; ++oy) {
                    const int yy = tile_y + oy;
                    if (yy < 0 || yy >= tile_rows) continue;
                    for (int ox = -1; ox <= 1; ++ox) {
                        const int xx = tile_x + ox;
                        if (xx < 0 || xx >= tile_cols) continue;
                        const size_t nidx = tile_index(frame, xx, yy);
                        if (nidx >= before.size() || !before[nidx].accepted) continue;
                        neighbor_dx.push_back(before[nidx].dx);
                        neighbor_dy.push_back(before[nidx].dy);
                    }
                }
                if (neighbor_dx.size() < 5 || neighbor_dy.size() < 5) continue;
                std::sort(neighbor_dx.begin(), neighbor_dx.end());
                std::sort(neighbor_dy.begin(), neighbor_dy.end());
                const int median_dx = neighbor_dx[neighbor_dx.size() / 2u];
                const int median_dy = neighbor_dy[neighbor_dy.size() / 2u];
                if (std::abs(before[idx].dx - median_dx) >= 4 || std::abs(before[idx].dy - median_dy) >= 4) {
                    offsets[idx].dx = median_dx;
                    offsets[idx].dy = median_dy;
                    result.changed_offsets += 1;
                }
            }
        }
    }
    return result;
}

inline SampledTileOffset sample_tile_alignment_offset_bilinear(
    const std::vector<TileAlignmentOffset>& offsets,
    size_t frame,
    int col,
    int row,
    int width,
    int height,
    int tile_cols,
    int tile_rows
) {
    SampledTileOffset sampled;
    if (tile_cols <= 0 || tile_rows <= 0 || width <= 0 || height <= 0) return sampled;
    auto tile_index = [tile_cols, tile_rows](size_t frame_index, int tile_x, int tile_y) {
        return (frame_index * static_cast<size_t>(tile_rows) + static_cast<size_t>(tile_y))
            * static_cast<size_t>(tile_cols) + static_cast<size_t>(tile_x);
    };
    const double gx = ((static_cast<double>(col) + 0.5) * static_cast<double>(tile_cols) / static_cast<double>(width)) - 0.5;
    const double gy = ((static_cast<double>(row) + 0.5) * static_cast<double>(tile_rows) / static_cast<double>(height)) - 0.5;
    const int x0 = std::max(0, std::min(tile_cols - 1, static_cast<int>(std::floor(gx))));
    const int y0 = std::max(0, std::min(tile_rows - 1, static_cast<int>(std::floor(gy))));
    const int x1 = std::max(0, std::min(tile_cols - 1, x0 + 1));
    const int y1 = std::max(0, std::min(tile_rows - 1, y0 + 1));
    const double wx = std::max(0.0, std::min(1.0, gx - static_cast<double>(x0)));
    const double wy = std::max(0.0, std::min(1.0, gy - static_cast<double>(y0)));
    const std::array<std::pair<int, int>, 4> corners = {{{x0, y0}, {x1, y0}, {x0, y1}, {x1, y1}}};
    const std::array<double, 4> weights = {{
        (1.0 - wx) * (1.0 - wy),
        wx * (1.0 - wy),
        (1.0 - wx) * wy,
        wx * wy,
    }};
    double total_weight = 0.0;
    double dx = 0.0;
    double dy = 0.0;
    for (size_t i = 0; i < corners.size(); ++i) {
        const size_t idx = tile_index(frame, corners[i].first, corners[i].second);
        if (idx >= offsets.size() || !offsets[idx].accepted) continue;
        total_weight += weights[i];
        dx += static_cast<double>(offsets[idx].dx) * weights[i];
        dy += static_cast<double>(offsets[idx].dy) * weights[i];
    }
    if (total_weight <= 0.0) return sampled;
    sampled.dx = static_cast<int>(std::round(dx / total_weight));
    sampled.dy = static_cast<int>(std::round(dy / total_weight));
    sampled.accepted = true;
    return sampled;
}

std::vector<SampledTileOffset> build_tile_alignment_offset_field(
    const std::vector<TileAlignmentOffset>& offsets,
    size_t frame,
    int width,
    int height,
    int tile_cols,
    int tile_rows
) {
    std::vector<SampledTileOffset> field(static_cast<size_t>(width) * static_cast<size_t>(height));
    parallel_for_rows(height, [&](int row) {
        const size_t base = static_cast<size_t>(row) * static_cast<size_t>(width);
        for (int col = 0; col < width; ++col) {
            field[base + static_cast<size_t>(col)] = sample_tile_alignment_offset_bilinear(
                offsets,
                frame,
                col,
                row,
                width,
                height,
                tile_cols,
                tile_rows
            );
        }
    });
    return field;
}

ReducedBayerFrame average_reduced_bayer_frames_global_aligned(
    const std::vector<RawFrameData>& frames,
    int out_width,
    int out_height,
    std::vector<AlignmentOffset>& offsets,
    int& alignment_failures,
    RawMergeTiming* timing = nullptr
) {
    const auto reduce_start = std::chrono::steady_clock::now();
    ReducedBayerFrame out;
    if (frames.empty()) return out;
    std::vector<ReducedBayerFrame> reduced_frames;
    reduced_frames.reserve(frames.size());
    for (const auto& frame : frames) {
        reduced_frames.push_back(downsample_raw_bayer_area(frame, out_width, out_height));
    }
    out = reduced_frames.front();
    std::fill(out.values.begin(), out.values.end(), 0.0f);
    offsets.clear();
    offsets.push_back({frames.front().index, 0, 0, 0.0, true});
    std::vector<AlignmentOffset> local_offsets(reduced_frames.size());
    local_offsets[0] = offsets.front();
    const auto reduce_done = std::chrono::steady_clock::now();
    const auto align_start = reduce_done;
    for (size_t i = 1; i < reduced_frames.size(); ++i) {
        local_offsets[i] = find_reduced_alignment_offset(reduced_frames.front(), reduced_frames[i], frames[i].index);
        if (!local_offsets[i].accepted) alignment_failures += 1;
    }
    const auto align_done = std::chrono::steady_clock::now();
    const auto merge_start = align_done;
    for (int row = 0; row < out_height; ++row) {
        for (int col = 0; col < out_width; ++col) {
            float total = reduced_bayer_value_at_unchecked(reduced_frames.front(), row, col);
            int count = 1;
            for (size_t i = 1; i < reduced_frames.size(); ++i) {
                const auto& offset = local_offsets[i];
                if (!offset.accepted) continue;
                const int yy = row + offset.dy;
                const int xx = col + offset.dx;
                if (yy < 0 || yy >= out_height || xx < 0 || xx >= out_width) continue;
                total += reduced_bayer_value_at_unchecked(reduced_frames[i], yy, xx);
                count += 1;
            }
            out.values[static_cast<size_t>(row) * static_cast<size_t>(out_width) + static_cast<size_t>(col)] =
                total / static_cast<float>(count);
        }
    }
    const auto merge_done = std::chrono::steady_clock::now();
    offsets = local_offsets;
    if (timing != nullptr) {
        timing->reduce_ms += elapsed_ms(reduce_start, reduce_done);
        timing->align_ms += elapsed_ms(align_start, align_done);
        timing->merge_ms += elapsed_ms(merge_start, merge_done);
    }
    return out;
}

ReducedBayerFrame average_reduced_bayer_frames_motion_aware(
    const std::vector<RawFrameData>& frames,
    int out_width,
    int out_height,
    std::vector<AlignmentOffset>& offsets,
    int& alignment_failures,
    RawMotionMergeTelemetry& motion,
    RawMergeTiming* timing = nullptr
) {
    const auto reduce_start = std::chrono::steady_clock::now();
    ReducedBayerFrame out;
    if (frames.empty()) return out;
    std::vector<ReducedBayerFrame> reduced_frames;
    reduced_frames.reserve(frames.size());
    for (const auto& frame : frames) {
        reduced_frames.push_back(downsample_raw_bayer_area(frame, out_width, out_height));
    }
    out = reduced_frames.front();
    std::fill(out.values.begin(), out.values.end(), 0.0f);
    offsets.clear();
    offsets.push_back({frames.front().index, 0, 0, 0.0, true});
    std::vector<AlignmentOffset> local_offsets(reduced_frames.size());
    local_offsets[0] = offsets.front();
    const auto reduce_done = std::chrono::steady_clock::now();
    const auto align_start = reduce_done;
    for (size_t i = 1; i < reduced_frames.size(); ++i) {
        local_offsets[i] = find_reduced_alignment_offset(reduced_frames.front(), reduced_frames[i], frames[i].index);
        if (!local_offsets[i].accepted) alignment_failures += 1;
    }
    const auto align_done = std::chrono::steady_clock::now();
    const auto merge_start = align_done;
    constexpr float kBaseMotionThreshold = 0.018f;
    constexpr float kRelativeMotionThreshold = 0.12f;
    std::vector<uint16_t> counts(static_cast<size_t>(out_width) * static_cast<size_t>(out_height), 1);
    parallel_for_rows(out_height, [&](int row) {
        const size_t base = static_cast<size_t>(row) * static_cast<size_t>(out_width);
        for (int col = 0; col < out_width; ++col) {
            out.values[base + static_cast<size_t>(col)] =
                reduced_bayer_value_at_unchecked(reduced_frames.front(), row, col);
        }
    });
    motion.rejected_samples = 0;
    motion.raw_rejected_samples = 0;
    motion.total_samples = 0;
    std::vector<int64_t> raw_rejected_by_row(static_cast<size_t>(out_height), 0);
    std::vector<int64_t> rejected_by_row(static_cast<size_t>(out_height), 0);
    std::vector<int64_t> total_by_row(static_cast<size_t>(out_height), 0);
    std::vector<uint8_t> raw_mask(static_cast<size_t>(out_width) * static_cast<size_t>(out_height), 0);
    std::vector<uint8_t> stable_mask(static_cast<size_t>(out_width) * static_cast<size_t>(out_height), 0);
    for (size_t i = 1; i < reduced_frames.size(); ++i) {
        const auto& offset = local_offsets[i];
        if (!offset.accepted) continue;
        std::fill(raw_mask.begin(), raw_mask.end(), 0);
        std::fill(stable_mask.begin(), stable_mask.end(), 0);
        parallel_for_rows(out_height, [&](int row) {
            int64_t row_total = 0;
            int64_t row_raw_rejected = 0;
            const size_t base = static_cast<size_t>(row) * static_cast<size_t>(out_width);
            for (int col = 0; col < out_width; ++col) {
                const int yy = row + offset.dy;
                const int xx = col + offset.dx;
                if (yy < 0 || yy >= out_height || xx < 0 || xx >= out_width) continue;
                const float reference = reduced_bayer_value_at_unchecked(reduced_frames.front(), row, col);
                const float candidate = reduced_bayer_value_at_unchecked(reduced_frames[i], yy, xx);
                const float threshold = kBaseMotionThreshold + kRelativeMotionThreshold * std::max(reference, candidate);
                row_total += 1;
                if (std::abs(candidate - reference) > threshold) {
                    raw_mask[base + static_cast<size_t>(col)] = 1;
                    row_raw_rejected += 1;
                }
            }
            total_by_row[static_cast<size_t>(row)] += row_total;
            raw_rejected_by_row[static_cast<size_t>(row)] += row_raw_rejected;
        });
        parallel_for_rows(out_height, [&](int row) {
            int64_t row_rejected = 0;
            for (int col = 0; col < out_width; ++col) {
                int neighborhood_rejections = 0;
                for (int dy = -1; dy <= 1; ++dy) {
                    const int yy = row + dy;
                    if (yy < 0 || yy >= out_height) continue;
                    const size_t ybase = static_cast<size_t>(yy) * static_cast<size_t>(out_width);
                    for (int dx = -1; dx <= 1; ++dx) {
                        const int xx = col + dx;
                        if (xx < 0 || xx >= out_width) continue;
                        neighborhood_rejections += raw_mask[ybase + static_cast<size_t>(xx)] != 0 ? 1 : 0;
                    }
                }
                if (neighborhood_rejections >= 3) {
                    stable_mask[static_cast<size_t>(row) * static_cast<size_t>(out_width) + static_cast<size_t>(col)] = 1;
                    row_rejected += 1;
                }
            }
            rejected_by_row[static_cast<size_t>(row)] += row_rejected;
        });
        parallel_for_rows(out_height, [&](int row) {
            const size_t base = static_cast<size_t>(row) * static_cast<size_t>(out_width);
            for (int col = 0; col < out_width; ++col) {
                const size_t idx = base + static_cast<size_t>(col);
                if (stable_mask[idx] != 0) continue;
                const int yy = row + offset.dy;
                const int xx = col + offset.dx;
                if (yy < 0 || yy >= out_height || xx < 0 || xx >= out_width) continue;
                out.values[idx] += reduced_bayer_value_at_unchecked(reduced_frames[i], yy, xx);
                counts[idx] += 1;
            }
        });
    }
    parallel_for_rows(out_height, [&](int row) {
        const size_t base = static_cast<size_t>(row) * static_cast<size_t>(out_width);
        for (int col = 0; col < out_width; ++col) {
            const size_t idx = base + static_cast<size_t>(col);
            out.values[idx] /= static_cast<float>(std::max<uint16_t>(1, counts[idx]));
        }
    });
    const auto merge_done = std::chrono::steady_clock::now();
    offsets = local_offsets;
    for (size_t row = 0; row < rejected_by_row.size(); ++row) {
        motion.rejected_samples += rejected_by_row[row];
        motion.raw_rejected_samples += raw_rejected_by_row[row];
        motion.total_samples += total_by_row[row];
    }
    if (timing != nullptr) {
        timing->reduce_ms += elapsed_ms(reduce_start, reduce_done);
        timing->align_ms += elapsed_ms(align_start, align_done);
        timing->merge_ms += elapsed_ms(merge_start, merge_done);
    }
    return out;
}

ReducedBayerFrame average_reduced_bayer_frames_tile_motion_aware(
    const std::vector<RawFrameData>& frames,
    int out_width,
    int out_height,
    std::vector<AlignmentOffset>& offsets,
    std::vector<TileAlignmentOffset>& tile_offsets,
    int& tile_alignment_smoothed_count,
    int& alignment_failures,
    RawMotionMergeTelemetry& motion,
    RawMergeTiming* timing = nullptr
) {
    const auto reduce_start = std::chrono::steady_clock::now();
    ReducedBayerFrame out;
    if (frames.empty()) return out;
    constexpr int kTileCols = 12;
    constexpr int kTileRows = 9;
    std::vector<ReducedBayerFrame> reduced_frames;
    reduced_frames.reserve(frames.size());
    for (const auto& frame : frames) {
        reduced_frames.push_back(downsample_raw_bayer_area(frame, out_width, out_height));
    }
    out = reduced_frames.front();
    offsets.clear();
    offsets.push_back({frames.front().index, 0, 0, 0.0, true});
    tile_offsets.clear();
    std::vector<AlignmentOffset> local_offsets(reduced_frames.size());
    local_offsets[0] = offsets.front();
    std::vector<TileAlignmentOffset> local_tile_offsets(reduced_frames.size() * kTileCols * kTileRows);
    std::vector<TileAlignmentOffset> tile_telemetry_offsets;
    tile_telemetry_offsets.reserve((reduced_frames.size() > 1 ? reduced_frames.size() - 1 : 0) * kTileCols * kTileRows);
    const auto reduce_done = std::chrono::steady_clock::now();
    const auto align_start = reduce_done;
    for (size_t i = 1; i < reduced_frames.size(); ++i) {
        local_offsets[i] = find_reduced_alignment_offset(reduced_frames.front(), reduced_frames[i], frames[i].index);
        if (!local_offsets[i].accepted) alignment_failures += 1;
        for (int ty = 0; ty < kTileRows; ++ty) {
            for (int tx = 0; tx < kTileCols; ++tx) {
                const size_t idx = (i * kTileRows + static_cast<size_t>(ty)) * kTileCols + static_cast<size_t>(tx);
                local_tile_offsets[idx] = find_reduced_tile_alignment_offset(
                    reduced_frames.front(),
                    reduced_frames[i],
                    frames[i].index,
                    tx,
                    ty,
                    kTileCols,
                    kTileRows,
                    local_offsets[i]
                );
                tile_telemetry_offsets.push_back(local_tile_offsets[idx]);
                if (!local_tile_offsets[idx].accepted) {
                    alignment_failures += 1;
                }
            }
        }
    }
    const TileAlignmentSmoothingResult smoothing = smooth_tile_alignment_offsets_median_3x3(
        local_tile_offsets,
        reduced_frames.size(),
        kTileCols,
        kTileRows
    );
    tile_alignment_smoothed_count += smoothing.changed_offsets;
    tile_telemetry_offsets.clear();
    tile_telemetry_offsets.reserve((reduced_frames.size() > 1 ? reduced_frames.size() - 1 : 0) * kTileCols * kTileRows);
    for (size_t i = 1; i < reduced_frames.size(); ++i) {
        for (int ty = 0; ty < kTileRows; ++ty) {
            for (int tx = 0; tx < kTileCols; ++tx) {
                const size_t idx = (i * kTileRows + static_cast<size_t>(ty)) * kTileCols + static_cast<size_t>(tx);
                tile_telemetry_offsets.push_back(local_tile_offsets[idx]);
            }
        }
    }
    const auto align_done = std::chrono::steady_clock::now();
    const auto merge_start = align_done;
    constexpr float kBaseMotionThreshold = 0.018f;
    constexpr float kRelativeMotionThreshold = 0.12f;
    std::vector<uint16_t> counts(static_cast<size_t>(out_width) * static_cast<size_t>(out_height), 1);
    parallel_for_rows(out_height, [&](int row) {
        const size_t base = static_cast<size_t>(row) * static_cast<size_t>(out_width);
        for (int col = 0; col < out_width; ++col) {
            out.values[base + static_cast<size_t>(col)] =
                reduced_bayer_value_at_unchecked(reduced_frames.front(), row, col);
        }
    });
    motion.rejected_samples = 0;
    motion.raw_rejected_samples = 0;
    motion.total_samples = 0;
    std::vector<int64_t> raw_rejected_by_row(static_cast<size_t>(out_height), 0);
    std::vector<int64_t> rejected_by_row(static_cast<size_t>(out_height), 0);
    std::vector<int64_t> total_by_row(static_cast<size_t>(out_height), 0);
    std::vector<uint8_t> raw_mask(static_cast<size_t>(out_width) * static_cast<size_t>(out_height), 0);
    std::vector<uint8_t> stable_mask(static_cast<size_t>(out_width) * static_cast<size_t>(out_height), 0);
    for (size_t i = 1; i < reduced_frames.size(); ++i) {
        if (!local_offsets[i].accepted) continue;
        const std::vector<SampledTileOffset> offset_field = build_tile_alignment_offset_field(
            local_tile_offsets,
            i,
            out_width,
            out_height,
            kTileCols,
            kTileRows
        );
        std::fill(raw_mask.begin(), raw_mask.end(), 0);
        std::fill(stable_mask.begin(), stable_mask.end(), 0);
        parallel_for_rows(out_height, [&](int row) {
            int64_t row_total = 0;
            int64_t row_raw_rejected = 0;
            const size_t base = static_cast<size_t>(row) * static_cast<size_t>(out_width);
            for (int col = 0; col < out_width; ++col) {
                const SampledTileOffset& tile = offset_field[base + static_cast<size_t>(col)];
                if (!tile.accepted) continue;
                const int yy = row + tile.dy;
                const int xx = col + tile.dx;
                if (yy < 0 || yy >= out_height || xx < 0 || xx >= out_width) continue;
                const float reference = reduced_bayer_value_at_unchecked(reduced_frames.front(), row, col);
                const float candidate = reduced_bayer_value_at_unchecked(reduced_frames[i], yy, xx);
                const float threshold = kBaseMotionThreshold + kRelativeMotionThreshold * std::max(reference, candidate);
                row_total += 1;
                if (std::abs(candidate - reference) > threshold) {
                    raw_mask[base + static_cast<size_t>(col)] = 1;
                    row_raw_rejected += 1;
                }
            }
            total_by_row[static_cast<size_t>(row)] += row_total;
            raw_rejected_by_row[static_cast<size_t>(row)] += row_raw_rejected;
        });
        parallel_for_rows(out_height, [&](int row) {
            int64_t row_rejected = 0;
            for (int col = 0; col < out_width; ++col) {
                int neighborhood_rejections = 0;
                for (int dy = -1; dy <= 1; ++dy) {
                    const int yy = row + dy;
                    if (yy < 0 || yy >= out_height) continue;
                    const size_t ybase = static_cast<size_t>(yy) * static_cast<size_t>(out_width);
                    for (int dx = -1; dx <= 1; ++dx) {
                        const int xx = col + dx;
                        if (xx < 0 || xx >= out_width) continue;
                        neighborhood_rejections += raw_mask[ybase + static_cast<size_t>(xx)] != 0 ? 1 : 0;
                    }
                }
                if (neighborhood_rejections >= 3) {
                    stable_mask[static_cast<size_t>(row) * static_cast<size_t>(out_width) + static_cast<size_t>(col)] = 1;
                    row_rejected += 1;
                }
            }
            rejected_by_row[static_cast<size_t>(row)] += row_rejected;
        });
        parallel_for_rows(out_height, [&](int row) {
            const size_t base = static_cast<size_t>(row) * static_cast<size_t>(out_width);
            for (int col = 0; col < out_width; ++col) {
                const size_t idx = base + static_cast<size_t>(col);
                if (stable_mask[idx] != 0) continue;
                const SampledTileOffset& tile = offset_field[idx];
                if (!tile.accepted) continue;
                const int yy = row + tile.dy;
                const int xx = col + tile.dx;
                if (yy < 0 || yy >= out_height || xx < 0 || xx >= out_width) continue;
                out.values[idx] += reduced_bayer_value_at_unchecked(reduced_frames[i], yy, xx);
                counts[idx] += 1;
            }
        });
    }
    parallel_for_rows(out_height, [&](int row) {
        const size_t base = static_cast<size_t>(row) * static_cast<size_t>(out_width);
        for (int col = 0; col < out_width; ++col) {
            const size_t idx = base + static_cast<size_t>(col);
            out.values[idx] /= static_cast<float>(std::max<uint16_t>(1, counts[idx]));
        }
    });
    const auto merge_done = std::chrono::steady_clock::now();
    offsets = local_offsets;
    tile_offsets = tile_telemetry_offsets;
    for (size_t row = 0; row < rejected_by_row.size(); ++row) {
        motion.rejected_samples += rejected_by_row[row];
        motion.raw_rejected_samples += raw_rejected_by_row[row];
        motion.total_samples += total_by_row[row];
    }
    if (timing != nullptr) {
        timing->reduce_ms += elapsed_ms(reduce_start, reduce_done);
        timing->align_ms += elapsed_ms(align_start, align_done);
        timing->merge_ms += elapsed_ms(merge_start, merge_done);
    }
    return out;
}

std::string alignment_offsets_json(const std::vector<AlignmentOffset>& offsets) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < offsets.size(); ++i) {
        if (i > 0) out << ",";
        out << "{\"index\":" << offsets[i].index
            << ",\"dx\":" << offsets[i].dx
            << ",\"dy\":" << offsets[i].dy
            << ",\"score\":" << offsets[i].score
            << ",\"accepted\":" << (offsets[i].accepted ? "true" : "false")
            << "}";
    }
    out << "]";
    return out.str();
}

std::string tile_alignment_offsets_json(const std::vector<TileAlignmentOffset>& offsets) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < offsets.size(); ++i) {
        if (i > 0) out << ",";
        out << "{\"frame_index\":" << offsets[i].frame_index
            << ",\"tile_x\":" << offsets[i].tile_x
            << ",\"tile_y\":" << offsets[i].tile_y
            << ",\"dx\":" << offsets[i].dx
            << ",\"dy\":" << offsets[i].dy
            << ",\"score\":" << offsets[i].score
            << ",\"accepted\":" << (offsets[i].accepted ? "true" : "false")
            << "}";
    }
    out << "]";
    return out.str();
}

std::vector<float> demosaic_raw_bilinear_fast(const RawFrameData& frame, int out_width, int out_height) {
    const RawCfaPattern pattern = parse_raw_cfa_pattern(frame.cfa);
    std::vector<int> source_rows(static_cast<size_t>(out_height));
    std::vector<int> source_cols(static_cast<size_t>(out_width));
    for (int row = 0; row < out_height; ++row) {
        source_rows[static_cast<size_t>(row)] = std::min(
            frame.height - 1,
            static_cast<int>((static_cast<int64_t>(row) * frame.height) / std::max(1, out_height))
        );
    }
    for (int col = 0; col < out_width; ++col) {
        source_cols[static_cast<size_t>(col)] = std::min(
            frame.width - 1,
            static_cast<int>((static_cast<int64_t>(col) * frame.width) / std::max(1, out_width))
        );
    }
    const double red_gain = frame.gains[0];
    const double green_gain = (frame.gains[1] + frame.gains[2]) * 0.5;
    const double blue_gain = frame.gains[3];
    const auto transform = frame.transform;
    std::vector<float> rgb(static_cast<size_t>(out_width) * static_cast<size_t>(out_height) * 3u);
    for (int row = 0; row < out_height; ++row) {
        const int src_row = source_rows[static_cast<size_t>(row)];
        for (int col = 0; col < out_width; ++col) {
            const int src_col = source_cols[static_cast<size_t>(col)];
            const double r = raw_channel_average_fast(frame, pattern, src_row, src_col, 'R') * red_gain;
            const double g = raw_channel_average_fast(frame, pattern, src_row, src_col, 'G') * green_gain;
            const double b = raw_channel_average_fast(frame, pattern, src_row, src_col, 'B') * blue_gain;
            const double tr = transform[0] * r + transform[1] * g + transform[2] * b;
            const double tg = transform[3] * r + transform[4] * g + transform[5] * b;
            const double tb = transform[6] * r + transform[7] * g + transform[8] * b;
            const size_t out = (static_cast<size_t>(row) * static_cast<size_t>(out_width) + static_cast<size_t>(col)) * 3u;
            rgb[out + 0] = static_cast<float>(std::max(0.0, tr));
            rgb[out + 1] = static_cast<float>(std::max(0.0, tg));
            rgb[out + 2] = static_cast<float>(std::max(0.0, tb));
        }
    }
    return rgb;
}

std::vector<float> demosaic_reduced_bayer_fast(const ReducedBayerFrame& frame) {
    const double red_gain = frame.gains[0];
    const double green_gain = (frame.gains[1] + frame.gains[2]) * 0.5;
    const double blue_gain = frame.gains[3];
    const auto transform = frame.transform;
    std::vector<float> rgb(static_cast<size_t>(frame.width) * static_cast<size_t>(frame.height) * 3u);
    for (int row = 0; row < frame.height; ++row) {
        for (int col = 0; col < frame.width; ++col) {
            const double r = reduced_channel_average_fast(frame, row, col, 'R') * red_gain;
            const double g = reduced_channel_average_fast(frame, row, col, 'G') * green_gain;
            const double b = reduced_channel_average_fast(frame, row, col, 'B') * blue_gain;
            const double tr = transform[0] * r + transform[1] * g + transform[2] * b;
            const double tg = transform[3] * r + transform[4] * g + transform[5] * b;
            const double tb = transform[6] * r + transform[7] * g + transform[8] * b;
            const size_t out = (static_cast<size_t>(row) * static_cast<size_t>(frame.width) + static_cast<size_t>(col)) * 3u;
            rgb[out + 0] = static_cast<float>(std::max(0.0, tr));
            rgb[out + 1] = static_cast<float>(std::max(0.0, tg));
            rgb[out + 2] = static_cast<float>(std::max(0.0, tb));
        }
    }
    return rgb;
}

inline float avg2f(float a, float b) {
    return (a + b) * 0.5f;
}

inline float avg4f(float a, float b, float c, float d) {
    return (a + b + c + d) * 0.25f;
}

inline std::array<float, 3> reduced_bayer_rgb_at_direct(const ReducedBayerFrame& frame, int row, int col) {
    const float red_gain = static_cast<float>(frame.gains[0]);
    const float green_gain = static_cast<float>((frame.gains[1] + frame.gains[2]) * 0.5);
    const float blue_gain = static_cast<float>(frame.gains[3]);
    float r = 0.0f;
    float g = 0.0f;
    float b = 0.0f;
    const float center = reduced_bayer_value_at_clamped(frame, row, col);
    const char color = raw_color_at_pattern(frame.pattern, row, col);
    if (color == 'R') {
        r = center;
        g = avg4f(
            reduced_bayer_value_at_clamped(frame, row - 1, col),
            reduced_bayer_value_at_clamped(frame, row + 1, col),
            reduced_bayer_value_at_clamped(frame, row, col - 1),
            reduced_bayer_value_at_clamped(frame, row, col + 1)
        );
        b = avg4f(
            reduced_bayer_value_at_clamped(frame, row - 1, col - 1),
            reduced_bayer_value_at_clamped(frame, row - 1, col + 1),
            reduced_bayer_value_at_clamped(frame, row + 1, col - 1),
            reduced_bayer_value_at_clamped(frame, row + 1, col + 1)
        );
    } else if (color == 'B') {
        b = center;
        g = avg4f(
            reduced_bayer_value_at_clamped(frame, row - 1, col),
            reduced_bayer_value_at_clamped(frame, row + 1, col),
            reduced_bayer_value_at_clamped(frame, row, col - 1),
            reduced_bayer_value_at_clamped(frame, row, col + 1)
        );
        r = avg4f(
            reduced_bayer_value_at_clamped(frame, row - 1, col - 1),
            reduced_bayer_value_at_clamped(frame, row - 1, col + 1),
            reduced_bayer_value_at_clamped(frame, row + 1, col - 1),
            reduced_bayer_value_at_clamped(frame, row + 1, col + 1)
        );
    } else if (color == 'G') {
        g = center;
        const bool red_horizontal = raw_color_at_pattern(frame.pattern, row, col - 1) == 'R'
            || raw_color_at_pattern(frame.pattern, row, col + 1) == 'R';
        if (red_horizontal) {
            r = avg2f(
                reduced_bayer_value_at_clamped(frame, row, col - 1),
                reduced_bayer_value_at_clamped(frame, row, col + 1)
            );
            b = avg2f(
                reduced_bayer_value_at_clamped(frame, row - 1, col),
                reduced_bayer_value_at_clamped(frame, row + 1, col)
            );
        } else {
            r = avg2f(
                reduced_bayer_value_at_clamped(frame, row - 1, col),
                reduced_bayer_value_at_clamped(frame, row + 1, col)
            );
            b = avg2f(
                reduced_bayer_value_at_clamped(frame, row, col - 1),
                reduced_bayer_value_at_clamped(frame, row, col + 1)
            );
        }
    } else {
        r = reduced_channel_average_fast(frame, row, col, 'R');
        g = reduced_channel_average_fast(frame, row, col, 'G');
        b = reduced_channel_average_fast(frame, row, col, 'B');
    }
    r *= red_gain;
    g *= green_gain;
    b *= blue_gain;
    return {
        std::max(0.0f, static_cast<float>(frame.transform[0]) * r + static_cast<float>(frame.transform[1]) * g + static_cast<float>(frame.transform[2]) * b),
        std::max(0.0f, static_cast<float>(frame.transform[3]) * r + static_cast<float>(frame.transform[4]) * g + static_cast<float>(frame.transform[5]) * b),
        std::max(0.0f, static_cast<float>(frame.transform[6]) * r + static_cast<float>(frame.transform[7]) * g + static_cast<float>(frame.transform[8]) * b),
    };
}

inline std::array<float, 3> reduced_bayer_rgb_at_direct_interior(const ReducedBayerFrame& frame, int row, int col) {
    const float red_gain = static_cast<float>(frame.gains[0]);
    const float green_gain = static_cast<float>((frame.gains[1] + frame.gains[2]) * 0.5);
    const float blue_gain = static_cast<float>(frame.gains[3]);
    float r = 0.0f;
    float g = 0.0f;
    float b = 0.0f;
    const float center = reduced_bayer_value_at_unchecked(frame, row, col);
    const char color = raw_color_at_pattern(frame.pattern, row, col);
    if (color == 'R') {
        r = center;
        g = avg4f(
            reduced_bayer_value_at_unchecked(frame, row - 1, col),
            reduced_bayer_value_at_unchecked(frame, row + 1, col),
            reduced_bayer_value_at_unchecked(frame, row, col - 1),
            reduced_bayer_value_at_unchecked(frame, row, col + 1)
        );
        b = avg4f(
            reduced_bayer_value_at_unchecked(frame, row - 1, col - 1),
            reduced_bayer_value_at_unchecked(frame, row - 1, col + 1),
            reduced_bayer_value_at_unchecked(frame, row + 1, col - 1),
            reduced_bayer_value_at_unchecked(frame, row + 1, col + 1)
        );
    } else if (color == 'B') {
        b = center;
        g = avg4f(
            reduced_bayer_value_at_unchecked(frame, row - 1, col),
            reduced_bayer_value_at_unchecked(frame, row + 1, col),
            reduced_bayer_value_at_unchecked(frame, row, col - 1),
            reduced_bayer_value_at_unchecked(frame, row, col + 1)
        );
        r = avg4f(
            reduced_bayer_value_at_unchecked(frame, row - 1, col - 1),
            reduced_bayer_value_at_unchecked(frame, row - 1, col + 1),
            reduced_bayer_value_at_unchecked(frame, row + 1, col - 1),
            reduced_bayer_value_at_unchecked(frame, row + 1, col + 1)
        );
    } else {
        g = center;
        const bool red_horizontal = raw_color_at_pattern(frame.pattern, row, col - 1) == 'R'
            || raw_color_at_pattern(frame.pattern, row, col + 1) == 'R';
        if (red_horizontal) {
            r = avg2f(
                reduced_bayer_value_at_unchecked(frame, row, col - 1),
                reduced_bayer_value_at_unchecked(frame, row, col + 1)
            );
            b = avg2f(
                reduced_bayer_value_at_unchecked(frame, row - 1, col),
                reduced_bayer_value_at_unchecked(frame, row + 1, col)
            );
        } else {
            r = avg2f(
                reduced_bayer_value_at_unchecked(frame, row - 1, col),
                reduced_bayer_value_at_unchecked(frame, row + 1, col)
            );
            b = avg2f(
                reduced_bayer_value_at_unchecked(frame, row, col - 1),
                reduced_bayer_value_at_unchecked(frame, row, col + 1)
            );
        }
    }
    r *= red_gain;
    g *= green_gain;
    b *= blue_gain;
    return {
        std::max(0.0f, static_cast<float>(frame.transform[0]) * r + static_cast<float>(frame.transform[1]) * g + static_cast<float>(frame.transform[2]) * b),
        std::max(0.0f, static_cast<float>(frame.transform[3]) * r + static_cast<float>(frame.transform[4]) * g + static_cast<float>(frame.transform[5]) * b),
        std::max(0.0f, static_cast<float>(frame.transform[6]) * r + static_cast<float>(frame.transform[7]) * g + static_cast<float>(frame.transform[8]) * b),
    };
}

inline float clamp01f(float value) {
    return value < 0.0f ? 0.0f : (value > 1.0f ? 1.0f : value);
}

inline std::array<float, 3> reduced_bayer_rgb_at_malvar_approx_interior(const ReducedBayerFrame& frame, int row, int col) {
    // edge_aware_green: conservative Malvar-style correction for green at red/blue sites.
    const char color = raw_color_at_pattern(frame.pattern, row, col);
    if (color != 'R' && color != 'B') return reduced_bayer_rgb_at_direct_interior(frame, row, col);
    const float center = reduced_bayer_value_at_unchecked(frame, row, col);
    const float cross = avg4f(
        reduced_bayer_value_at_unchecked(frame, row - 1, col),
        reduced_bayer_value_at_unchecked(frame, row + 1, col),
        reduced_bayer_value_at_unchecked(frame, row, col - 1),
        reduced_bayer_value_at_unchecked(frame, row, col + 1)
    );
    const float diagonal = avg4f(
        reduced_bayer_value_at_unchecked(frame, row - 1, col - 1),
        reduced_bayer_value_at_unchecked(frame, row - 1, col + 1),
        reduced_bayer_value_at_unchecked(frame, row + 1, col - 1),
        reduced_bayer_value_at_unchecked(frame, row + 1, col + 1)
    );
    const float corrected_green = clamp01f(cross + (center - diagonal) * 0.125f);
    const float green_gain = static_cast<float>((frame.gains[1] + frame.gains[2]) * 0.5);
    const float red_gain = static_cast<float>(frame.gains[0]);
    const float blue_gain = static_cast<float>(frame.gains[3]);
    float r = color == 'R' ? center * red_gain : diagonal * red_gain;
    float g = corrected_green * green_gain;
    float b = color == 'B' ? center * blue_gain : diagonal * blue_gain;
    if (color == 'R') {
        b = avg4f(
            reduced_bayer_value_at_unchecked(frame, row - 1, col - 1),
            reduced_bayer_value_at_unchecked(frame, row - 1, col + 1),
            reduced_bayer_value_at_unchecked(frame, row + 1, col - 1),
            reduced_bayer_value_at_unchecked(frame, row + 1, col + 1)
        ) * blue_gain;
    } else {
        r = avg4f(
            reduced_bayer_value_at_unchecked(frame, row - 1, col - 1),
            reduced_bayer_value_at_unchecked(frame, row - 1, col + 1),
            reduced_bayer_value_at_unchecked(frame, row + 1, col - 1),
            reduced_bayer_value_at_unchecked(frame, row + 1, col + 1)
        ) * red_gain;
    }
    return {
        std::max(0.0f, static_cast<float>(frame.transform[0]) * r + static_cast<float>(frame.transform[1]) * g + static_cast<float>(frame.transform[2]) * b),
        std::max(0.0f, static_cast<float>(frame.transform[3]) * r + static_cast<float>(frame.transform[4]) * g + static_cast<float>(frame.transform[5]) * b),
        std::max(0.0f, static_cast<float>(frame.transform[6]) * r + static_cast<float>(frame.transform[7]) * g + static_cast<float>(frame.transform[8]) * b),
    };
}

inline uint8_t raw_display_byte(double value, double exposure, double highlight_rolloff, double shadow_lift) {
    value = std::max(0.0, value * exposure);
    value = value / (1.0 + value * highlight_rolloff);
    if (shadow_lift > 0.0) {
        const double shadow_weight = std::max(0.0, std::min(1.0, (0.55 - value) / 0.55));
        value += shadow_lift * shadow_weight * value * (1.0 - value) * 0.85;
    }
    value = std::pow(std::max(0.0, std::min(1.0, value)), 1.0 / 2.2);
    return static_cast<uint8_t>(std::round(value * 255.0));
}

std::vector<uint8_t> build_raw_display_lut(double exposure, double highlight_rolloff, double shadow_lift) {
    constexpr int kLutSize = 4096;
    constexpr double kMaxInput = 8.0;
    std::vector<uint8_t> lut(static_cast<size_t>(kLutSize));
    for (int i = 0; i < kLutSize; ++i) {
        const double normalized = static_cast<double>(i) / static_cast<double>(kLutSize - 1);
        const double value = normalized * kMaxInput;
        lut[static_cast<size_t>(i)] = raw_display_byte(value, exposure, highlight_rolloff, shadow_lift);
    }
    return lut;
}

inline uint8_t raw_display_byte_lut(const std::vector<uint8_t>& lut, float value) {
    constexpr float kMaxInput = 8.0f;
    if (value <= 0.0f) return lut.front();
    if (value >= kMaxInput) return lut.back();
    const float scaled = (value / kMaxInput) * static_cast<float>(lut.size() - 1);
    return lut[static_cast<size_t>(scaled + 0.5f)];
}

RenderStyleProfile style_profile_for_name(const std::string& style) {
    if (style == "Google") return {"Google", 1.06f, 1.08f, 1.0f, 1.0f, 0.86f, 0.30f, 0.035f, 1.02f, 0.06f, 0.18f, 0.18f};
    if (style == "Apple") return {"Apple", 1.02f, 0.98f, 1.03f, 0.98f, 0.82f, 0.25f, 0.025f, 0.98f, 0.02f, 0.08f, 0.15f};
    if (style == "Samsung") return {"Samsung", 1.18f, 1.14f, 1.02f, 1.02f, 0.88f, 0.38f, 0.05f, 1.04f, 0.10f, 0.22f, 0.10f};
    if (style == "Xiaomi") return {"Xiaomi", 1.24f, 1.18f, 1.04f, 1.0f, 0.90f, 0.42f, 0.06f, 1.05f, 0.12f, 0.25f, 0.08f};
    return {"Neutral", 1.0f, 1.0f, 1.0f, 1.0f, 0.85f, 0.35f, 0.025f, 1.0f, 0.03f, 0.10f, 0.14f};
}

inline uint8_t style_channel(float value) {
    return static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, value)) + 0.5f);
}

inline void apply_render_style_rgb(const RenderStyleProfile& profile, uint8_t& r, uint8_t& g, uint8_t& b) {
    if (profile.saturation == 1.0f && profile.contrast == 1.0f && profile.red_bias == 1.0f && profile.blue_bias == 1.0f) return;
    const float rf = static_cast<float>(r) * profile.red_bias;
    const float gf = static_cast<float>(g);
    const float bf = static_cast<float>(b) * profile.blue_bias;
    const float luma = 0.2126f * rf + 0.7152f * gf + 0.0722f * bf;
    float sr = luma + (rf - luma) * profile.saturation;
    float sg = luma + (gf - luma) * profile.saturation;
    float sb = luma + (bf - luma) * profile.saturation;
    sr = 128.0f + (sr - 128.0f) * profile.contrast;
    sg = 128.0f + (sg - 128.0f) * profile.contrast;
    sb = 128.0f + (sb - 128.0f) * profile.contrast;
    r = style_channel(sr);
    g = style_channel(sg);
    b = style_channel(sb);
}

inline void apply_highlight_color_guard_rgb(uint8_t& r, uint8_t& g, uint8_t& b) {
    const float rf = static_cast<float>(r);
    const float gf = static_cast<float>(g);
    const float bf = static_cast<float>(b);
    const float max_channel = std::max({rf, gf, bf});
    if (max_channel < 224.0f) return;
    const float luma = 0.2126f * rf + 0.7152f * gf + 0.0722f * bf;
    const float blend = std::max(0.0f, std::min(0.45f, (max_channel - 224.0f) / 31.0f * 0.45f));
    r = style_channel(rf * (1.0f - blend) + luma * blend);
    g = style_channel(gf * (1.0f - blend) + luma * blend);
    b = style_channel(bf * (1.0f - blend) + luma * blend);
}

inline float raw_luma_byte(const std::vector<uint8_t>& rgba, size_t pixel) {
    const size_t base = pixel * 4u;
    return 0.2126f * static_cast<float>(rgba[base + 0])
        + 0.7152f * static_cast<float>(rgba[base + 1])
        + 0.0722f * static_cast<float>(rgba[base + 2]);
}

inline bool is_shadow_purple_artifact_pixel(const std::vector<uint8_t>& rgba, size_t pixel) {
    const size_t base = pixel * 4u;
    const float r = static_cast<float>(rgba[base + 0]);
    const float g = static_cast<float>(rgba[base + 1]);
    const float b = static_cast<float>(rgba[base + 2]);
    const float luma = 0.2126f * r + 0.7152f * g + 0.0722f * b;
    if (luma > 170.0f) return false;
    const float chroma_span = std::max({r, g, b}) - std::min({r, g, b});
    if (chroma_span < 18.0f) return false;
    return b > g * 1.18f && r > g * 1.08f;
}

RawArtifactTelemetry apply_raw_shadow_purple_guard(
    std::vector<uint8_t>& rgba,
    int width,
    int height
) {
    RawArtifactTelemetry telemetry;
    if (width < 3 || height < 3) return telemetry;
    const std::vector<uint8_t> source = rgba;
    std::vector<int64_t> inspected_by_row(static_cast<size_t>(height), 0);
    std::vector<int64_t> purple_before_by_row(static_cast<size_t>(height), 0);
    std::vector<int64_t> purple_after_by_row(static_cast<size_t>(height), 0);
    std::vector<int64_t> suppressed_by_row(static_cast<size_t>(height), 0);
    parallel_for_rows(height - 2, [&](int worker_row) {
        const int row = worker_row + 1;
        int64_t inspected = 0;
        int64_t purple_before = 0;
        int64_t purple_after = 0;
        int64_t suppressed = 0;
        for (int col = 1; col < width - 1; ++col) {
            const size_t pixel = static_cast<size_t>(row) * static_cast<size_t>(width) + static_cast<size_t>(col);
            inspected += 1;
            if (!is_shadow_purple_artifact_pixel(source, pixel)) {
                if (is_shadow_purple_artifact_pixel(rgba, pixel)) purple_after += 1;
                continue;
            }
            purple_before += 1;
            const size_t base = pixel * 4u;
            const float luma = raw_luma_byte(source, pixel);
            const float shadow_weight = std::max(0.0f, std::min(1.0f, (170.0f - luma) / 170.0f));
            const float blend = 0.45f * shadow_weight;
            for (int channel = 0; channel < 3; ++channel) {
                const float center = static_cast<float>(source[base + static_cast<size_t>(channel)]);
                rgba[base + static_cast<size_t>(channel)] = style_channel(center * (1.0f - blend) + luma * blend);
            }
            if (is_shadow_purple_artifact_pixel(rgba, pixel)) {
                purple_after += 1;
            } else {
                suppressed += 1;
            }
        }
        inspected_by_row[static_cast<size_t>(row)] = inspected;
        purple_before_by_row[static_cast<size_t>(row)] = purple_before;
        purple_after_by_row[static_cast<size_t>(row)] = purple_after;
        suppressed_by_row[static_cast<size_t>(row)] = suppressed;
    });
    for (size_t row = 0; row < inspected_by_row.size(); ++row) {
        telemetry.inspected_pixels += inspected_by_row[row];
        telemetry.purple_pixels_before += purple_before_by_row[row];
        telemetry.purple_pixels_after += purple_after_by_row[row];
        telemetry.purple_suppressed_pixels += suppressed_by_row[row];
    }
    return telemetry;
}

void apply_raw_radial_chroma_shading_guard(
    std::vector<uint8_t>& rgba,
    int width,
    int height
) {
    if (width <= 1 || height <= 1) return;
    const float cx = (static_cast<float>(width) - 1.0f) * 0.5f;
    const float cy = (static_cast<float>(height) - 1.0f) * 0.5f;
    const float max_radius = std::sqrt(cx * cx + cy * cy);
    if (max_radius <= 0.0f) return;
    parallel_for_rows(height, [&](int row) {
        const float dy = static_cast<float>(row) - cy;
        for (int col = 0; col < width; ++col) {
            const float dx = static_cast<float>(col) - cx;
            const float radius = std::sqrt(dx * dx + dy * dy) / max_radius;
            const float edge_weight = std::max(0.0f, std::min(1.0f, (radius - 0.58f) / 0.42f));
            if (edge_weight <= 0.0f) continue;
            const size_t pixel = static_cast<size_t>(row) * static_cast<size_t>(width) + static_cast<size_t>(col);
            const size_t base = pixel * 4u;
            const float luma = raw_luma_byte(rgba, pixel);
            const float blend = 0.18f * edge_weight;
            for (int channel = 0; channel < 3; ++channel) {
                const float center = static_cast<float>(rgba[base + static_cast<size_t>(channel)]);
                rgba[base + static_cast<size_t>(channel)] = style_channel(center * (1.0f - blend) + luma * blend);
            }
        }
    });
}

void apply_raw_chroma_guard(
    std::vector<uint8_t>& rgba,
    int width,
    int height,
    const RenderStyleProfile& profile
) {
    if (width < 3 || height < 3 || profile.chroma_denoise <= 0.0f) return;
    const std::vector<uint8_t> source = rgba;
    parallel_for_rows(height - 2, [&](int worker_row) {
        const int row = worker_row + 1;
        for (int col = 1; col < width - 1; ++col) {
            const size_t pixel = static_cast<size_t>(row) * static_cast<size_t>(width) + static_cast<size_t>(col);
            const size_t base = pixel * 4u;
            const float luma = raw_luma_byte(source, pixel);
            float neighbor_rgb[3] = {0.0f, 0.0f, 0.0f};
            int neighbor_count = 0;
            for (int dy = -1; dy <= 1; ++dy) {
                const int yy = row + dy;
                const size_t ybase = static_cast<size_t>(yy) * static_cast<size_t>(width);
                for (int dx = -1; dx <= 1; ++dx) {
                    if (dx == 0 && dy == 0) continue;
                    const int xx = col + dx;
                    const size_t nbase = (ybase + static_cast<size_t>(xx)) * 4u;
                    neighbor_rgb[0] += static_cast<float>(source[nbase + 0]);
                    neighbor_rgb[1] += static_cast<float>(source[nbase + 1]);
                    neighbor_rgb[2] += static_cast<float>(source[nbase + 2]);
                    neighbor_count += 1;
                }
            }
            if (neighbor_count <= 0) continue;
            const float inv = 1.0f / static_cast<float>(neighbor_count);
            neighbor_rgb[0] *= inv;
            neighbor_rgb[1] *= inv;
            neighbor_rgb[2] *= inv;
            const float neighbor_luma = 0.2126f * neighbor_rgb[0] + 0.7152f * neighbor_rgb[1] + 0.0722f * neighbor_rgb[2];
            const float shadow_weight = std::max(0.0f, std::min(1.0f, (180.0f - luma) / 180.0f));
            const float blend = profile.chroma_denoise * shadow_weight;
            if (blend <= 0.0f) continue;
            for (int channel = 0; channel < 3; ++channel) {
                const float center = static_cast<float>(source[base + static_cast<size_t>(channel)]);
                const float center_chroma = center - luma;
                const float neighbor_chroma = neighbor_rgb[channel] - neighbor_luma;
                rgba[base + static_cast<size_t>(channel)] = style_channel(
                    luma + center_chroma * (1.0f - blend) + neighbor_chroma * blend
                );
            }
        }
    });
}

RawNeutralCastTelemetry apply_raw_neutral_cast_guard(
    std::vector<uint8_t>& rgba,
    int width,
    int height
) {
    RawNeutralCastTelemetry telemetry;
    if (width <= 0 || height <= 0 || rgba.empty()) return telemetry;
    const int pixel_count = width * height;
    const int step = std::max(1, pixel_count / 8192);
    double r_sum = 0.0;
    double g_sum = 0.0;
    double b_sum = 0.0;
    int64_t samples = 0;
    for (int idx = 0; idx < pixel_count; idx += step) {
        const size_t base = static_cast<size_t>(idx) * 4u;
        const float r = static_cast<float>(rgba[base + 0]);
        const float g = static_cast<float>(rgba[base + 1]);
        const float b = static_cast<float>(rgba[base + 2]);
        const float max_channel = std::max({r, g, b});
        const float min_channel = std::min({r, g, b});
        const float luma = 0.2126f * r + 0.7152f * g + 0.0722f * b;
        if (luma < 42.0f || luma > 220.0f) continue;
        if ((max_channel - min_channel) > std::max(10.0f, luma * 0.10f)) continue;
        r_sum += r;
        g_sum += g;
        b_sum += b;
        samples += 1;
    }
    telemetry.neutral_samples = samples;
    if (samples < 96) return telemetry;
    const double r_avg = r_sum / static_cast<double>(samples);
    const double g_avg = g_sum / static_cast<double>(samples);
    const double b_avg = b_sum / static_cast<double>(samples);
    const double gray = (r_avg + g_avg + b_avg) / 3.0;
    if (gray <= 1.0) return telemetry;
    telemetry.red_gain = std::max(0.94, std::min(1.06, gray / std::max(1.0, r_avg)));
    telemetry.green_gain = std::max(0.94, std::min(1.06, gray / std::max(1.0, g_avg)));
    telemetry.blue_gain = std::max(0.94, std::min(1.06, gray / std::max(1.0, b_avg)));
    const double max_delta = std::max({
        std::abs(telemetry.red_gain - 1.0),
        std::abs(telemetry.green_gain - 1.0),
        std::abs(telemetry.blue_gain - 1.0),
    });
    if (max_delta < 0.012) return telemetry;
    telemetry.applied = true;
    parallel_for_rows(height, [&](int row) {
        const size_t row_base = static_cast<size_t>(row) * static_cast<size_t>(width);
        for (int col = 0; col < width; ++col) {
            const size_t base = (row_base + static_cast<size_t>(col)) * 4u;
            rgba[base + 0] = style_channel(static_cast<float>(rgba[base + 0]) * static_cast<float>(telemetry.red_gain));
            rgba[base + 1] = style_channel(static_cast<float>(rgba[base + 1]) * static_cast<float>(telemetry.green_gain));
            rgba[base + 2] = style_channel(static_cast<float>(rgba[base + 2]) * static_cast<float>(telemetry.blue_gain));
        }
    });
    return telemetry;
}

void apply_raw_photo_finishing(
    std::vector<uint8_t>& rgba,
    int width,
    int height,
    const RenderStyleProfile& profile
) {
    if (width < 3 || height < 3 || (profile.local_contrast <= 0.0f && profile.sharpening <= 0.0f)) return;
    const std::vector<uint8_t> source = rgba;
    parallel_for_rows(height - 2, [&](int worker_row) {
        const int row = worker_row + 1;
        for (int col = 1; col < width - 1; ++col) {
            const size_t pixel = static_cast<size_t>(row) * static_cast<size_t>(width) + static_cast<size_t>(col);
            const size_t left = pixel - 1u;
            const size_t right = pixel + 1u;
            const size_t up = pixel - static_cast<size_t>(width);
            const size_t down = pixel + static_cast<size_t>(width);
            const float center_luma = raw_luma_byte(source, pixel);
            const float neighbor_luma = (
                raw_luma_byte(source, left) +
                raw_luma_byte(source, right) +
                raw_luma_byte(source, up) +
                raw_luma_byte(source, down)
            ) * 0.25f;
            const float luma_detail = (center_luma - neighbor_luma) * profile.local_contrast;
            const size_t base = pixel * 4u;
            const size_t left_base = left * 4u;
            const size_t right_base = right * 4u;
            const size_t up_base = up * 4u;
            const size_t down_base = down * 4u;
            for (int channel = 0; channel < 3; ++channel) {
                const float center = static_cast<float>(source[base + static_cast<size_t>(channel)]);
                const float neighbor = (
                    static_cast<float>(source[left_base + static_cast<size_t>(channel)]) +
                    static_cast<float>(source[right_base + static_cast<size_t>(channel)]) +
                    static_cast<float>(source[up_base + static_cast<size_t>(channel)]) +
                    static_cast<float>(source[down_base + static_cast<size_t>(channel)])
                ) * 0.25f;
                rgba[base + static_cast<size_t>(channel)] = style_channel(
                    center + (center - neighbor) * profile.sharpening + luma_detail
                );
            }
        }
    });
}

RawRenderResult render_reduced_bayer_to_rgba_fused(
    const ReducedBayerFrame& frame,
    const std::string& demosaic_mode,
    const RenderStyleProfile& style_profile,
    const std::string& lens_shading_mode
) {
    const bool use_malvar = demosaic_mode == "malvar_approx";
    std::vector<double> luminance;
    luminance.reserve(std::min<size_t>(static_cast<size_t>(frame.width) * static_cast<size_t>(frame.height), 4096u));
    const int pixel_count = frame.width * frame.height;
    const int step = std::max(1, pixel_count / 4096);
    for (int idx = 0; idx < pixel_count; idx += step) {
        const int row = idx / frame.width;
        const int col = idx - row * frame.width;
        const auto rgb = (row > 0 && row < frame.height - 1 && col > 0 && col < frame.width - 1)
            ? (use_malvar ? reduced_bayer_rgb_at_malvar_approx_interior(frame, row, col) : reduced_bayer_rgb_at_direct_interior(frame, row, col))
            : reduced_bayer_rgb_at_direct(frame, row, col);
        luminance.push_back(0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]);
    }
    std::sort(luminance.begin(), luminance.end());
    const double p50 = luminance.empty() ? 0.0 : luminance[static_cast<size_t>(std::min<int>(luminance.size() - 1, static_cast<int>(luminance.size() * 0.50)))];
    const double p95 = luminance.empty() ? 1.0 : luminance[static_cast<size_t>(std::min<int>(luminance.size() - 1, static_cast<int>(luminance.size() * 0.95)))];
    const double p99 = luminance.empty() ? 1.0 : luminance[static_cast<size_t>(std::min<int>(luminance.size() - 1, static_cast<int>(luminance.size() * 0.99)))];
    const double p95_exposure = p95 > 0.0001
        ? (static_cast<double>(style_profile.target_p95) / p95) * static_cast<double>(style_profile.exposure_bias)
        : 1.0;
    const double p99_exposure_limit = p99 > 0.0001 ? 0.98 / p99 : p95_exposure;
    const double exposure = std::min(p95_exposure, p99_exposure_limit);
    const double adaptive_shadow_lift = p50 < 0.08 ? std::min(0.04, (0.08 - p50) * 0.55) : 0.0;
    const double shadow_lift = std::min(0.10, static_cast<double>(style_profile.shadow_lift) + adaptive_shadow_lift);
    const auto display_lut = build_raw_display_lut(exposure, style_profile.highlight_rolloff, shadow_lift);
    std::vector<uint8_t> rgba(static_cast<size_t>(frame.width) * static_cast<size_t>(frame.height) * 4u);
    parallel_for_rows(frame.height, [&](int row) {
        for (int col = 0; col < frame.width; ++col) {
            const auto rgb = (row > 0 && row < frame.height - 1 && col > 0 && col < frame.width - 1)
                ? (use_malvar ? reduced_bayer_rgb_at_malvar_approx_interior(frame, row, col) : reduced_bayer_rgb_at_direct_interior(frame, row, col))
                : reduced_bayer_rgb_at_direct(frame, row, col);
            const size_t out = (static_cast<size_t>(row) * static_cast<size_t>(frame.width) + static_cast<size_t>(col)) * 4u;
            uint8_t r = raw_display_byte_lut(display_lut, rgb[0]);
            uint8_t g = raw_display_byte_lut(display_lut, rgb[1]);
            uint8_t b = raw_display_byte_lut(display_lut, rgb[2]);
            apply_render_style_rgb(style_profile, r, g, b);
            apply_highlight_color_guard_rgb(r, g, b);
            rgba[out + 0] = r;
            rgba[out + 1] = g;
            rgba[out + 2] = b;
            rgba[out + 3] = 255;
        }
    });
    if (!frame.lens_shading_usable && lens_shading_mode != "off") {
        apply_raw_radial_chroma_shading_guard(rgba, frame.width, frame.height);
    }
    apply_raw_chroma_guard(rgba, frame.width, frame.height, style_profile);
    RawNeutralCastTelemetry neutral_cast = apply_raw_neutral_cast_guard(rgba, frame.width, frame.height);
    const RawArtifactTelemetry artifacts = apply_raw_shadow_purple_guard(rgba, frame.width, frame.height);
    apply_raw_photo_finishing(rgba, frame.width, frame.height, style_profile);
    return {
        std::move(rgba),
        {
            exposure,
            p50,
            p95,
            p99,
            static_cast<double>(style_profile.highlight_rolloff),
            shadow_lift
        },
        artifacts,
        neutral_cast
    };
}

std::vector<uint8_t> render_linear_rgb_to_rgba(const std::vector<float>& rgb, int width, int height) {
    std::vector<double> luminance;
    luminance.reserve(std::min<size_t>(rgb.size() / 3u, 4096u));
    const int step = std::max(1, (width * height) / 4096);
    for (int idx = 0; idx < width * height; idx += step) {
        const size_t base = static_cast<size_t>(idx) * 3u;
        luminance.push_back(0.2126 * rgb[base] + 0.7152 * rgb[base + 1] + 0.0722 * rgb[base + 2]);
    }
    std::sort(luminance.begin(), luminance.end());
    const double p95 = luminance.empty() ? 1.0 : luminance[static_cast<size_t>(std::min<int>(luminance.size() - 1, static_cast<int>(luminance.size() * 0.95)))];
    const double exposure = p95 > 0.0001 ? 0.85 / p95 : 1.0;
    std::vector<uint8_t> rgba(static_cast<size_t>(width) * static_cast<size_t>(height) * 4u);
    for (int idx = 0; idx < width * height; ++idx) {
        const size_t in = static_cast<size_t>(idx) * 3u;
        const size_t out = static_cast<size_t>(idx) * 4u;
        for (int ch = 0; ch < 3; ++ch) {
            double value = std::max(0.0, static_cast<double>(rgb[in + ch]) * exposure);
            value = value / (1.0 + value * 0.35);
            value = std::pow(std::max(0.0, std::min(1.0, value)), 1.0 / 2.2);
            rgba[out + static_cast<size_t>(ch)] = static_cast<uint8_t>(std::round(value * 255.0));
        }
        rgba[out + 3] = 255;
    }
    return rgba;
}

std::string process_raw_burst_native(
    const std::string& manifest_path,
    const std::string& output_rgba_path,
    const std::string& preview_rgba_path,
    int preview_max_edge,
    const std::string& quality_mode,
    const std::string& demosaic_mode,
    const std::string& merge_mode,
    const std::string& render_style,
    const std::string& lens_shading_mode
) {
    // RAW merge modes: single, no-alignment average, global alignment, and
    // reference-protected motion-aware average.
    const auto total_start = std::chrono::steady_clock::now();
    const std::string manifest = read_text_file(manifest_path);
    if (manifest.empty()) return raw_processor_error_json("missing burst manifest");
    if (parse_string_key(manifest, "format") != "RAW_SENSOR") {
        return raw_processor_error_json("unsupported non-RAW burst processing");
    }
    const auto frames = parse_burst_frames(manifest);
    if (frames.empty()) return raw_processor_error_json("burst manifest has no frames");
    const auto parse_done = std::chrono::steady_clock::now();
    double best_score = -1.0;
    RawFrameData best;
    std::vector<RawFrameData> candidates;
    int rejected = 0;
    for (const auto& frame : frames) {
        RawFrameData candidate = parse_raw_frame_data(frame, false);
        if (lens_shading_mode == "off" || lens_shading_mode == "radial") {
            candidate.lens_shading_usable = false;
            candidate.lens_shading_values.clear();
        }
        if (candidate.raw16_path.empty() || candidate.width <= 0 || candidate.height <= 0) {
            rejected += 1;
            continue;
        }
        if (raw_color_at(candidate.cfa, 0, 0) == '?') {
            rejected += 1;
            continue;
        }
        double score = candidate.sharpness_score;
        if (score < 0.0) {
            load_raw_frame_bytes(candidate, false);
            if (!raw_frame_has_bytes(candidate)) {
                rejected += 1;
                continue;
            }
            score = score_raw_green_sharpness(candidate);
            candidate.bytes.clear();
            candidate.mapped_bytes.reset();
        }
        candidate.sharpness_score = score;
        candidates.push_back(candidate);
        if (score > best_score) {
            best_score = score;
            best = std::move(candidate);
        }
    }
    const auto score_done = std::chrono::steady_clock::now();
    if (best_score < 0.0) return raw_processor_error_json("unsupported color_filter_arrangement or raw16 missing");
    if (!raw_frame_has_bytes(best)) {
        load_raw_frame_bytes(best, true);
    }
    if (!raw_frame_has_bytes(best)) return raw_processor_error_json("selected raw16 file is missing or empty");
    const auto load_selected_done = std::chrono::steady_clock::now();
    const std::string raw_quality_mode =
        quality_mode == "balanced_2400" ? "balanced_2400" :
        (quality_mode == "full_res" ? "full_res" : "fast_1600");
    const std::string raw_demosaic_mode = demosaic_mode == "malvar_approx" ? "malvar_approx" : "bilinear_fast";
    const RenderStyleProfile style_profile = style_profile_for_name(render_style);
    const std::string raw_lens_shading_mode_request =
        lens_shading_mode == "off" ? "off" :
        (lens_shading_mode == "radial" ? "radial" : "auto");
    const std::string raw_merge_mode =
        merge_mode == "raw_average_tile_motion_aware" ? "raw_average_tile_motion_aware" :
        (merge_mode == "raw_average_motion_aware" ? "raw_average_motion_aware" :
        (merge_mode == "raw_average_global_aligned" ? "raw_average_global_aligned" :
        (merge_mode == "raw_average_no_alignment" ? "raw_average_no_alignment" : "raw_single_frame")));
    const int render_max_edge =
        raw_quality_mode == "balanced_2400" ? 2400 :
        (raw_quality_mode == "full_res" ? std::max(best.width, best.height) : 1600);
    const double render_scale = std::min(1.0, static_cast<double>(render_max_edge) / static_cast<double>(std::max(best.width, best.height)));
    const int render_width = std::max(1, static_cast<int>(std::round(best.width * render_scale)));
    const int render_height = std::max(1, static_cast<int>(std::round(best.height * render_scale)));
    int merge_count = 1;
    int merge_rejected = 0;
    int incompatible_rejected = 0;
    int sharpness_rejected = 0;
    int exposure_rejected = 0;
    int alignment_failures = 0;
    int tile_alignment_smoothed_count = 0;
    bool exposure_consistent = true;
    std::vector<AlignmentOffset> alignment_offsets;
    std::vector<TileAlignmentOffset> tile_alignment_offsets;
    RawMotionMergeTelemetry motion_telemetry;
    ReducedBayerFrame reduced_bayer;
    RawMergeTiming merge_timing;
    const auto merge_load_start = std::chrono::steady_clock::now();
    double merge_load_ms = 0.0;
    if (raw_merge_mode == "raw_average_no_alignment"
        || raw_merge_mode == "raw_average_global_aligned"
        || raw_merge_mode == "raw_average_motion_aware"
        || raw_merge_mode == "raw_average_tile_motion_aware") {
        std::vector<RawFrameData> merge_frames;
        merge_frames.push_back(best);
        for (auto& candidate : candidates) {
            if (candidate.index == best.index) {
                continue;
            }
            if (candidate.raw16_path.empty()
                || candidate.width != best.width
                || candidate.height != best.height
                || candidate.cfa != best.cfa) {
                merge_rejected += 1;
                incompatible_rejected += 1;
                continue;
            }
            if (!raw_sharpness_compatible(best_score, candidate)) {
                merge_rejected += 1;
                sharpness_rejected += 1;
                continue;
            }
            if (!raw_exposure_compatible(best, candidate)) {
                merge_rejected += 1;
                exposure_rejected += 1;
                exposure_consistent = false;
                continue;
            }
            if (!raw_frame_has_bytes(candidate)) {
                load_raw_frame_bytes(candidate, true);
            }
            if (!raw_frame_has_bytes(candidate)) {
                merge_rejected += 1;
                continue;
            }
            merge_frames.push_back(std::move(candidate));
        }
        if (merge_frames.empty()) {
            merge_frames.push_back(best);
            exposure_consistent = false;
        }
        merge_count = static_cast<int>(merge_frames.size());
        const auto merge_load_done = std::chrono::steady_clock::now();
        merge_load_ms = elapsed_ms(merge_load_start, merge_load_done);
        if (raw_merge_mode == "raw_average_tile_motion_aware") {
            reduced_bayer = average_reduced_bayer_frames_tile_motion_aware(
                merge_frames,
                render_width,
                render_height,
                alignment_offsets,
                tile_alignment_offsets,
                tile_alignment_smoothed_count,
                alignment_failures,
                motion_telemetry,
                &merge_timing
            );
        } else if (raw_merge_mode == "raw_average_motion_aware") {
            reduced_bayer = average_reduced_bayer_frames_motion_aware(
                merge_frames,
                render_width,
                render_height,
                alignment_offsets,
                alignment_failures,
                motion_telemetry,
                &merge_timing
            );
        } else if (raw_merge_mode == "raw_average_global_aligned") {
            reduced_bayer = average_reduced_bayer_frames_global_aligned(
                merge_frames,
                render_width,
                render_height,
                alignment_offsets,
                alignment_failures,
                &merge_timing
            );
        } else {
            reduced_bayer = average_reduced_bayer_frames(merge_frames, render_width, render_height, &merge_timing);
        }
    } else {
        const auto merge_load_done = std::chrono::steady_clock::now();
        merge_load_ms = elapsed_ms(merge_load_start, merge_load_done);
        const auto reduce_start = std::chrono::steady_clock::now();
        reduced_bayer = downsample_raw_bayer_area(best, render_width, render_height);
        merge_timing.reduce_ms = elapsed_ms(reduce_start, std::chrono::steady_clock::now());
    }
    const auto downsample_done = std::chrono::steady_clock::now();
    auto render_result = render_reduced_bayer_to_rgba_fused(
        reduced_bayer,
        raw_demosaic_mode,
        style_profile,
        raw_lens_shading_mode_request
    );
    std::string selected_merge_mode = raw_merge_mode;
    std::string raw_quality_fallback = "none";
    double requested_raw_shadow_purple_ratio_after = raw_shadow_purple_ratio_after(render_result.artifacts);
    const double requested_motion_rejected_ratio = motion_telemetry.total_samples > 0
        ? static_cast<double>(motion_telemetry.rejected_samples) / static_cast<double>(motion_telemetry.total_samples)
        : 0.0;
    const bool artifact_guard_fallback_needed = requested_raw_shadow_purple_ratio_after >= 0.05;
    const bool motion_guard_fallback_needed = requested_motion_rejected_ratio >= 0.18;
    if (raw_merge_mode != "raw_single_frame" && (artifact_guard_fallback_needed || motion_guard_fallback_needed)) {
        const auto fallback_reduce_start = std::chrono::steady_clock::now();
        ReducedBayerFrame fallback_bayer = downsample_raw_bayer_area(best, render_width, render_height);
        const double fallback_reduce_ms = elapsed_ms(fallback_reduce_start, std::chrono::steady_clock::now());
        RawRenderResult fallback_result = render_reduced_bayer_to_rgba_fused(
            fallback_bayer,
            raw_demosaic_mode,
            style_profile,
            raw_lens_shading_mode_request
        );
        const double fallback_ratio = raw_shadow_purple_ratio_after(fallback_result.artifacts);
        const bool fallback_improves_artifacts = fallback_ratio < requested_raw_shadow_purple_ratio_after;
        const bool fallback_keeps_artifacts_safe = fallback_ratio <= std::max(0.025, requested_raw_shadow_purple_ratio_after + 0.005);
        if ((artifact_guard_fallback_needed && fallback_improves_artifacts)
            || (motion_guard_fallback_needed && fallback_keeps_artifacts_safe)) {
            render_result = std::move(fallback_result);
            reduced_bayer = std::move(fallback_bayer);
            selected_merge_mode = "raw_single_frame";
            raw_quality_fallback = artifact_guard_fallback_needed ? "artifact_guard_single_frame" : "motion_guard_single_frame";
            merge_timing.reduce_ms += fallback_reduce_ms;
            merge_count = 1;
        }
    }
    const auto& rgba = render_result.rgba;
    const auto render_done = std::chrono::steady_clock::now();
    if (!write_binary_file(output_rgba_path, rgba)) {
        return raw_processor_error_json("could not write full RAW RGBA output");
    }
    int preview_width = 0;
    int preview_height = 0;
    if (preview_max_edge > 0 && !preview_rgba_path.empty()) {
        const int max_edge = std::max(1, preview_max_edge);
        const double scale = std::min(1.0, static_cast<double>(max_edge) / static_cast<double>(std::max(render_width, render_height)));
        preview_width = std::max(1, static_cast<int>(std::round(render_width * scale)));
        preview_height = std::max(1, static_cast<int>(std::round(render_height * scale)));
        const auto preview = downscale_rgba_bilinear(rgba, render_width, render_height, preview_width, preview_height);
        if (!write_binary_file(preview_rgba_path, preview)) {
            return raw_processor_error_json("could not write preview RAW RGBA output");
        }
    }
    const auto preview_done = std::chrono::steady_clock::now();
    const auto write_done = std::chrono::steady_clock::now();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"mode\":\"" << selected_merge_mode << "\","
        << "\"raw_reference_frame\":" << best.index << ","
        << "\"reference_frame\":" << best.index << ","
        << "\"used_frames\":" << merge_count << ","
        << "\"rejected_frames\":" << (rejected + merge_rejected + alignment_failures) << ","
        << "\"width\":" << render_width << ","
        << "\"height\":" << render_height << ","
        << "\"raw_width\":" << best.width << ","
        << "\"raw_height\":" << best.height << ","
        << "\"preview_width\":" << preview_width << ","
        << "\"preview_height\":" << preview_height << ","
        << "\"score\":" << best_score << ","
        << "\"source_format\":\"RAW_SENSOR\","
        << "\"raw_quality_mode\":\"" << raw_quality_mode << "\","
        << "\"raw_demosaic_mode\":\"" << raw_demosaic_mode << "\","
        << "\"raw_requested_merge_mode\":\"" << raw_merge_mode << "\","
        << "\"raw_merge_mode\":\"" << selected_merge_mode << "\","
        << "\"raw_quality_verdict\":\"" << raw_quality_verdict_for_artifacts(render_result.artifacts) << "\","
        << "\"raw_quality_fallback\":\"" << raw_quality_fallback << "\","
        << "\"raw_requested_shadow_purple_ratio_after\":" << requested_raw_shadow_purple_ratio_after << ","
        << "\"raw_requested_motion_rejected_ratio\":" << requested_motion_rejected_ratio << ","
        << "\"style_profile\":\"" << style_profile.name << "\","
        << "\"render_layer\":\"global_style_v1\","
        << "\"tone_map_exposure\":" << render_result.tone.exposure << ","
        << "\"tone_map_p50\":" << render_result.tone.p50 << ","
        << "\"tone_map_p95\":" << render_result.tone.p95 << ","
        << "\"tone_map_p99\":" << render_result.tone.p99 << ","
        << "\"tone_map_highlight_rolloff\":" << render_result.tone.highlight_rolloff << ","
        << "\"tone_map_shadow_lift\":" << render_result.tone.shadow_lift << ","
        << "\"merge_count\":" << merge_count << ","
        << "\"merge_rejected\":" << merge_rejected << ","
        << "\"incompatible_rejected\":" << incompatible_rejected << ","
        << "\"sharpness_rejected\":" << sharpness_rejected << ","
        << "\"exposure_rejected\":" << exposure_rejected << ","
        << "\"exposure_consistent\":" << (exposure_consistent ? "true" : "false") << ","
        << "\"alignment_offsets\":" << alignment_offsets_json(alignment_offsets) << ","
        << "\"alignment_failures\":" << alignment_failures << ","
        << "\"tile_alignment_grid\":\"12x9\","
        << "\"tile_alignment_acceptance\":\"conservative_score_0.035\","
        << "\"tile_alignment_smoothing\":\"median_3x3\","
        << "\"tile_alignment_sampling\":\"bilinear_offset_field\","
        << "\"tile_alignment_field_cached\":true,"
        << "\"tile_alignment_smoothed_count\":" << tile_alignment_smoothed_count << ","
        << "\"tile_alignment_offsets\":" << tile_alignment_offsets_json(tile_alignment_offsets) << ","
        << "\"motion_mask_mode\":\"spatial_3x3_min3\","
        << "\"motion_raw_rejected_samples\":" << motion_telemetry.raw_rejected_samples << ","
        << "\"motion_rejected_samples\":" << motion_telemetry.rejected_samples << ","
        << "\"motion_total_samples\":" << motion_telemetry.total_samples << ","
        << "\"motion_rejected_ratio\":" << (motion_telemetry.total_samples > 0
            ? static_cast<double>(motion_telemetry.rejected_samples) / static_cast<double>(motion_telemetry.total_samples)
            : 0.0) << ","
        << "\"render_max_edge\":" << render_max_edge << ","
        << "\"raw_downsample\":\"bayer_area\","
        << "\"raw_demosaic\":\"" << (raw_demosaic_mode == "malvar_approx" ? "malvar_approx" : "reduced_bayer_direct_bilinear") << "\","
        << "\"raw_render\":\"fused_rgba_interior_fast_photo_finish\","
        << "\"raw_photo_finishing\":{\"local_contrast\":" << style_profile.local_contrast
        << ",\"sharpening\":" << style_profile.sharpening
        << ",\"chroma_denoise\":" << style_profile.chroma_denoise << "},"
        << "\"raw_neutral_cast_guard\":\"gray_world_neutral_v1\","
        << "\"raw_neutral_cast_samples\":" << render_result.neutral_cast.neutral_samples << ","
        << "\"raw_neutral_cast_applied\":" << (render_result.neutral_cast.applied ? "true" : "false") << ","
        << "\"raw_neutral_cast_gains\":[" << render_result.neutral_cast.red_gain
        << "," << render_result.neutral_cast.green_gain
        << "," << render_result.neutral_cast.blue_gain << "],"
        << "\"raw_artifact_guard\":\"shadow_purple_v1\","
        << "\"raw_shadow_purple_pixels_before\":" << render_result.artifacts.purple_pixels_before << ","
        << "\"raw_shadow_purple_pixels_after\":" << render_result.artifacts.purple_pixels_after << ","
        << "\"raw_shadow_purple_suppressed_pixels\":" << render_result.artifacts.purple_suppressed_pixels << ","
        << "\"raw_shadow_purple_ratio_before\":" << (render_result.artifacts.inspected_pixels > 0
            ? static_cast<double>(render_result.artifacts.purple_pixels_before) / static_cast<double>(render_result.artifacts.inspected_pixels)
            : 0.0) << ","
        << "\"raw_shadow_purple_ratio_after\":" << (render_result.artifacts.inspected_pixels > 0
            ? static_cast<double>(render_result.artifacts.purple_pixels_after) / static_cast<double>(render_result.artifacts.inspected_pixels)
            : 0.0) << ","
        << "\"raw_color_gains_usable\":" << (reduced_bayer.gains_usable ? "true" : "false") << ","
        << "\"raw_color_transform_usable\":" << (reduced_bayer.transform_usable ? "true" : "false") << ","
        << "\"raw_color_matrix_mode\":\"" << (reduced_bayer.transform_usable ? "normalized_camera_transform" : "identity_fallback") << "\","
        << "\"raw_color_gain_mode\":\"green_normalized_clamped_0.55_2.60\","
        << "\"raw_lens_shading_request\":\"" << raw_lens_shading_mode_request << "\","
        << "\"raw_lens_shading_mode\":\"" << (reduced_bayer.lens_shading_usable
            ? "sensor_lens_shading_map"
            : (raw_lens_shading_mode_request == "off" ? "off" : "radial_chroma_guard_v1")) << "\","
        << "\"raw_lens_shading_map_used\":" << (reduced_bayer.lens_shading_usable ? "true" : "false") << ","
        << "\"raw_load_mode\":\"" << raw_frame_load_mode(best) << "\","
        << "\"preview_scale_mode\":\"bilinear\","
        << "\"native_timing_ms\":{"
        << "\"manifest_parse\":" << elapsed_ms(total_start, parse_done) << ","
        << "\"frame_score\":" << elapsed_ms(parse_done, score_done) << ","
        << "\"selected_load\":" << elapsed_ms(score_done, load_selected_done) << ","
        << "\"merge_load\":" << merge_load_ms << ","
        << "\"raw_reduce\":" << merge_timing.reduce_ms << ","
        << "\"alignment\":" << merge_timing.align_ms << ","
        << "\"merge\":" << merge_timing.merge_ms << ","
        << "\"render\":" << elapsed_ms(downsample_done, render_done) << ","
        << "\"preview\":" << elapsed_ms(render_done, preview_done) << ","
        << "\"write\":" << elapsed_ms(preview_done, write_done) << ","
        << "\"total\":" << elapsed_ms(total_start, write_done)
        << "},"
        << "\"render_mode\":\"" << selected_merge_mode << "\"}";
    return out.str();
}

}  // namespace

extern "C" JNIEXPORT jint JNICALL
Java_com_luvatrix_app_NativeVulkan_probeVulkan(JNIEnv *, jobject) {
    uint32_t extension_count = 0;
    VkResult result = vkEnumerateInstanceExtensionProperties(nullptr, &extension_count, nullptr);
    if (result != VK_SUCCESS) {
        LVX_LOGE("vkEnumerateInstanceExtensionProperties failed: %d", result);
        return 0;
    }
    LVX_LOGI("luvatrix vulkan probe ok extensions=%u", extension_count);
    return static_cast<jint>(extension_count);
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_luvatrix_app_NativeCameraProcessor_processYuvBurst(
    JNIEnv* env,
    jobject,
    jstring manifestPath,
    jstring outputRgbaPath,
    jstring previewRgbaPath,
    jint previewMaxEdge
) {
    const std::string result = process_yuv_burst_native(
        jstring_to_string(env, manifestPath),
        jstring_to_string(env, outputRgbaPath),
        jstring_to_string(env, previewRgbaPath),
        static_cast<int>(previewMaxEdge)
    );
    return env->NewStringUTF(result.c_str());
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_luvatrix_app_NativeCameraProcessor_processRawBurst(
    JNIEnv* env,
    jobject,
    jstring manifestPath,
    jstring outputRgbaPath,
    jstring previewRgbaPath,
    jint previewMaxEdge,
    jstring qualityMode,
    jstring demosaicMode,
    jstring mergeMode,
    jstring renderStyle,
    jstring lensShadingMode
) {
    const std::string result = process_raw_burst_native(
        jstring_to_string(env, manifestPath),
        jstring_to_string(env, outputRgbaPath),
        jstring_to_string(env, previewRgbaPath),
        static_cast<int>(previewMaxEdge),
        jstring_to_string(env, qualityMode),
        jstring_to_string(env, demosaicMode),
        jstring_to_string(env, mergeMode),
        jstring_to_string(env, renderStyle),
        jstring_to_string(env, lensShadingMode)
    );
    return env->NewStringUTF(result.c_str());
}

extern "C" JNIEXPORT void JNICALL
Java_com_luvatrix_app_NativeVulkan_setSurface(JNIEnv *env, jobject, jobject surface) {
    std::lock_guard<std::mutex> lock(g_mutex);
    destroy_vulkan(g_vk);
    if (surface == nullptr) {
        LVX_LOGI("native Vulkan surface cleared");
        return;
    }
    g_vk.window = ANativeWindow_fromSurface(env, surface);
    if (g_vk.window == nullptr) {
        LVX_LOGE("ANativeWindow_fromSurface returned null");
        return;
    }
    LVX_LOGI(
        "native Vulkan surface set window=%p size=%dx%d",
        g_vk.window,
        ANativeWindow_getWidth(g_vk.window),
        ANativeWindow_getHeight(g_vk.window)
    );
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_luvatrix_app_NativeVulkan_setBitmapGlyphTable(JNIEnv *env, jobject, jstring tableText) {
    if (tableText == nullptr) return JNI_FALSE;
    const char* raw = env->GetStringUTFChars(tableText, nullptr);
    if (raw == nullptr) return JNI_FALSE;
    std::string table(raw);
    env->ReleaseStringUTFChars(tableText, raw);

    BitmapFont parsed;
    bool ok = parse_bitmap_font_table(table, parsed);
    if (!ok) {
        LVX_LOGE("luvatrix bitmap glyph table parse failed");
        return JNI_FALSE;
    }
    std::lock_guard<std::mutex> lock(g_mutex);
    g_bitmap_font = std::move(parsed);
    LVX_LOGI(
        "luvatrix bitmap glyph table loaded glyphs=%zu size=%dx%d advance=%d",
        g_bitmap_font.glyphs.size(),
        g_bitmap_font.width,
        g_bitmap_font.height,
        g_bitmap_font.advance
    );
    return JNI_TRUE;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_luvatrix_app_NativeVulkan_presentRgba(
    JNIEnv *env,
    jobject,
    jbyteArray rgba,
    jint revision,
    jint width,
    jint height
) {
    if (rgba == nullptr || width <= 0 || height <= 0) return JNI_FALSE;
    size_t pixel_count = static_cast<size_t>(width) * static_cast<size_t>(height);
    if (pixel_count > std::numeric_limits<size_t>::max() / 4u) return JNI_FALSE;
    size_t byte_count = pixel_count * 4u;
    if (byte_count > static_cast<size_t>(std::numeric_limits<jsize>::max())) return JNI_FALSE;
    if (env->GetArrayLength(rgba) != static_cast<jsize>(byte_count)) return JNI_FALSE;

    std::vector<uint32_t> pixels(pixel_count);
    env->GetByteArrayRegion(
        rgba,
        0,
        static_cast<jsize>(byte_count),
        reinterpret_cast<jbyte*>(pixels.data())
    );
    if (env->ExceptionCheck()) return JNI_FALSE;
    rgba_to_bgra_in_place(reinterpret_cast<uint8_t*>(pixels.data()), pixel_count);

    std::lock_guard<std::mutex> lock(g_mutex);
    bool presented = render_rgba_matrix(
        g_vk,
        pixels,
        static_cast<int>(width),
        static_cast<int>(height)
    );
    if (presented && revision % 120 == 0) {
        LVX_LOGI(
            "luvatrix vulkan rgba revision=%d source=%dx%d display=%ux%u",
            revision,
            width,
            height,
            g_vk.extent.width,
            g_vk.extent.height
        );
    }
    return presented ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_luvatrix_app_NativeVulkan_presentScene(
    JNIEnv *env,
    jobject,
    jstring sceneJson,
    jint revision,
    jint width,
    jint height,
    jstring presentationMode
) {
    const char* raw = env->GetStringUTFChars(sceneJson, nullptr);
    if (raw == nullptr) return JNI_FALSE;
    std::string payload(raw);
    env->ReleaseStringUTFChars(sceneJson, raw);

    ParsedScene scene = parse_scene(payload);
    // Extract presentation mode from JNI parameter if provided, fallback to parsing from scene JSON
    if (presentationMode != nullptr) {
        const char* modeRaw = env->GetStringUTFChars(presentationMode, nullptr);
        if (modeRaw != nullptr) {
            scene.presentation_mode = std::string(modeRaw);
            env->ReleaseStringUTFChars(presentationMode, modeRaw);
        }
    }
    std::lock_guard<std::mutex> lock(g_mutex);
    g_vk.desired_width = std::max(1, static_cast<int>(width));
    g_vk.desired_height = std::max(1, static_cast<int>(height));
    g_retained_scene = std::move(scene);
    g_retained_scene_available = true;
    g_retained_scene_revision = static_cast<int>(revision);
    g_retained_scene_width = std::max(1, static_cast<int>(width));
    g_retained_scene_height = std::max(1, static_cast<int>(height));
    bool ok = render_scene_pixels(g_vk, g_retained_scene, width, height);
    if (ok && revision % 120 == 0) {
        LVX_LOGI(
            "luvatrix vulkan scene revision=%d size=%dx%d nodes=%d rects=%zu circles=%zu text=%zu rgba=%d,%d,%d,%d",
            revision,
            width,
            height,
            count_nodes(payload),
            g_retained_scene.rects.size(),
            g_retained_scene.circles.size(),
            g_retained_scene.texts.size(),
            g_retained_scene.background.r,
            g_retained_scene.background.g,
            g_retained_scene.background.b,
            g_retained_scene.background.a
        );
    }
    return ok ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_luvatrix_app_NativeVulkan_presentSceneBinary(
    JNIEnv *env,
    jobject,
    jbyteArray scenePacket,
    jint revision,
    jint width,
    jint height,
    jstring presentationMode
) {
    if (scenePacket == nullptr) return JNI_FALSE;
    const jsize packet_size = env->GetArrayLength(scenePacket);
    if (packet_size <= 0) return JNI_FALSE;
    jbyte* raw = env->GetByteArrayElements(scenePacket, nullptr);
    if (raw == nullptr) return JNI_FALSE;
    ParsedScene scene;
    const bool parsed = parse_scene_binary(reinterpret_cast<const uint8_t*>(raw), static_cast<size_t>(packet_size), scene);
    env->ReleaseByteArrayElements(scenePacket, raw, JNI_ABORT);
    if (!parsed) return JNI_FALSE;
    if (presentationMode != nullptr) {
        const char* mode_raw = env->GetStringUTFChars(presentationMode, nullptr);
        if (mode_raw != nullptr) {
            scene.presentation_mode = std::string(mode_raw);
            env->ReleaseStringUTFChars(presentationMode, mode_raw);
        }
    }
    std::lock_guard<std::mutex> lock(g_mutex);
    g_vk.desired_width = std::max(1, static_cast<int>(width));
    g_vk.desired_height = std::max(1, static_cast<int>(height));
    g_retained_scene = std::move(scene);
    g_retained_scene_available = true;
    g_retained_scene_revision = static_cast<int>(revision);
    g_retained_scene_width = std::max(1, static_cast<int>(width));
    g_retained_scene_height = std::max(1, static_cast<int>(height));
    const bool ok = render_scene_pixels(g_vk, g_retained_scene, width, height);
    if (ok && revision % 120 == 0) {
        LVX_LOGI(
            "luvatrix vulkan binary scene revision=%d size=%dx%d rects=%zu circles=%zu text=%zu rgba=%d,%d,%d,%d",
            revision,
            width,
            height,
            g_retained_scene.rects.size(),
            g_retained_scene.circles.size(),
            g_retained_scene.texts.size(),
            g_retained_scene.background.r,
            g_retained_scene.background.g,
            g_retained_scene.background.b,
            g_retained_scene.background.a
        );
    }
    return ok ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_luvatrix_app_NativeVulkan_presentSceneTransform(
    JNIEnv *,
    jobject,
    jint revision,
    jdouble contentOffsetX,
    jdouble contentOffsetY
) {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (!g_retained_scene_available) return JNI_FALSE;
    if (static_cast<int>(revision) <= g_retained_scene_revision) return JNI_TRUE;
    g_retained_scene_revision = static_cast<int>(revision);
    g_retained_scene.content_offset_x = static_cast<double>(contentOffsetX);
    g_retained_scene.content_offset_y = static_cast<double>(contentOffsetY);
    bool ok = render_scene_pixels(
        g_vk,
        g_retained_scene,
        g_retained_scene_width,
        g_retained_scene_height
    );
    return ok ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT void JNICALL
Java_com_luvatrix_app_NativeVulkan_setCameraPreviewEnabled(JNIEnv *, jobject, jboolean enabled) {
    std::lock_guard<std::mutex> lock(g_mutex);
    g_camera_primary.preview_enabled = enabled == JNI_TRUE;
    g_camera_secondary.preview_enabled = enabled == JNI_TRUE;
}

extern "C" JNIEXPORT void JNICALL
Java_com_luvatrix_app_NativeVulkan_setCameraCoverMode(JNIEnv *env, jobject, jstring mode) {
    if (mode == nullptr) return;
    const char* raw = env->GetStringUTFChars(mode, nullptr);
    if (raw == nullptr) return;
    std::string value(raw);
    env->ReleaseStringUTFChars(mode, raw);
    std::lock_guard<std::mutex> lock(g_mutex);
    g_camera_primary.cover_mode = value.empty() ? "cover_center" : value;
    g_camera_secondary.cover_mode = value.empty() ? "cover_center" : value;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_luvatrix_app_NativeVulkan_setCameraDownsampleMode(JNIEnv *env, jobject, jstring mode) {
    if (mode == nullptr) return JNI_FALSE;
    const char* raw = env->GetStringUTFChars(mode, nullptr);
    if (raw == nullptr) return JNI_FALSE;
    std::string value(raw);
    env->ReleaseStringUTFChars(mode, raw);
    std::lock_guard<std::mutex> lock(g_mutex);
    if (value == "natural") {
        g_downsample_filter = "natural";
        g_downsample_taps = 5;
        g_luma_smoothing = 0.08f;
        g_chroma_smoothing = 0.55f;
        g_edge_preserve = 0.65f;
        g_downsample_strength = 0.15f;
        g_downsample_mode = 0.0f;
    } else if (value == "clean") {
        g_downsample_filter = "clean";
        g_downsample_taps = 9;
        g_luma_smoothing = 0.24f;
        g_chroma_smoothing = 0.88f;
        g_edge_preserve = 0.62f;
        g_downsample_strength = 0.04f;
        g_downsample_mode = 1.0f;
    } else if (value == "lowlight") {
        g_downsample_filter = "lowlight";
        g_downsample_taps = 13;
        g_luma_smoothing = 0.50f;
        g_chroma_smoothing = 1.00f;
        g_edge_preserve = 0.50f;
        g_downsample_strength = 0.00f;
        g_downsample_mode = 2.0f;
    } else if (value == "detail") {
        g_downsample_filter = "detail";
        g_downsample_taps = 9;
        g_luma_smoothing = 0.08f;
        g_chroma_smoothing = 0.48f;
        g_edge_preserve = 0.78f;
        g_downsample_strength = 0.62f;
        g_downsample_mode = 3.0f;
    } else {
        return JNI_FALSE;
    }
    g_vk.camera_intermediate_ready = false;
    g_gpu_preview.downsample_filter = g_downsample_filter;
    g_gpu_preview.filter_preset = g_downsample_filter;
    g_gpu_preview.downsample_taps = g_downsample_taps;
    g_gpu_preview.filter_taps = g_downsample_taps;
        g_gpu_preview.downsample_strength = static_cast<double>(g_downsample_strength);
        g_gpu_preview.luma_smoothing = static_cast<double>(g_luma_smoothing);
        g_gpu_preview.chroma_smoothing = static_cast<double>(g_chroma_smoothing);
        g_gpu_preview.edge_preserve = static_cast<double>(g_edge_preserve);
        g_gpu_preview.convolution_layers = g_convolution_layers;
        g_gpu_preview.crop_fit_blend = static_cast<double>(g_crop_fit_blend);
        g_gpu_preview.downsample_last_error.clear();
    return JNI_TRUE;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_luvatrix_app_NativeVulkan_setCameraConvolutionLayers(JNIEnv *, jobject, jint layers) {
    uint32_t clamped = static_cast<uint32_t>(std::max(0, std::min(4, static_cast<int>(layers))));
    std::lock_guard<std::mutex> lock(g_mutex);
    g_convolution_layers = clamped;
    g_crop_fit_blend = static_cast<float>(clamped) / 4.0f;
    if (clamped == 0) {
        g_downsample_filter = "natural";
        g_downsample_taps = 5;
        g_luma_smoothing = 0.08f;
        g_chroma_smoothing = 0.55f;
        g_edge_preserve = 0.65f;
        g_downsample_strength = 0.15f;
        g_downsample_mode = 0.0f;
    } else if (clamped == 1) {
        g_downsample_filter = "layer1";
        g_downsample_taps = 5;
        g_luma_smoothing = 0.14f;
        g_chroma_smoothing = 0.68f;
        g_edge_preserve = 0.65f;
        g_downsample_strength = 0.10f;
        g_downsample_mode = 0.0f;
    } else if (clamped == 2) {
        g_downsample_filter = "layer2";
        g_downsample_taps = 9;
        g_luma_smoothing = 0.24f;
        g_chroma_smoothing = 0.82f;
        g_edge_preserve = 0.62f;
        g_downsample_strength = 0.04f;
        g_downsample_mode = 1.0f;
    } else if (clamped == 3) {
        g_downsample_filter = "layer3";
        g_downsample_taps = 13;
        g_luma_smoothing = 0.38f;
        g_chroma_smoothing = 0.94f;
        g_edge_preserve = 0.55f;
        g_downsample_strength = 0.00f;
        g_downsample_mode = 2.0f;
    } else {
        g_downsample_filter = "layer4";
        g_downsample_taps = 13;
        g_luma_smoothing = 0.50f;
        g_chroma_smoothing = 1.00f;
        g_edge_preserve = 0.50f;
        g_downsample_strength = 0.00f;
        g_downsample_mode = 2.0f;
    }
    g_vk.camera_intermediate_ready = false;
    g_gpu_preview.downsample_filter = g_downsample_filter;
    g_gpu_preview.filter_preset = g_downsample_filter;
    g_gpu_preview.downsample_taps = g_downsample_taps;
    g_gpu_preview.filter_taps = g_downsample_taps;
    g_gpu_preview.downsample_strength = static_cast<double>(g_downsample_strength);
    g_gpu_preview.luma_smoothing = static_cast<double>(g_luma_smoothing);
    g_gpu_preview.chroma_smoothing = static_cast<double>(g_chroma_smoothing);
    g_gpu_preview.edge_preserve = static_cast<double>(g_edge_preserve);
    g_gpu_preview.convolution_layers = g_convolution_layers;
    g_gpu_preview.crop_fit_blend = static_cast<double>(g_crop_fit_blend);
    g_gpu_preview.downsample_last_error.clear();
    return JNI_TRUE;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_luvatrix_app_NativeVulkan_setCameraColorMode(JNIEnv *env, jobject, jstring mode) {
    if (mode == nullptr) return JNI_FALSE;
    const char* raw = env->GetStringUTFChars(mode, nullptr);
    if (raw == nullptr) return JNI_FALSE;
    std::string value(raw);
    env->ReleaseStringUTFChars(mode, raw);
    std::lock_guard<std::mutex> lock(g_mutex);
    if (value == "auto") {
        g_color_mode = "auto";
        g_red_gain = 1.0f;
        g_green_gain = 1.0f;
        g_blue_gain = 1.0f;
        g_color_brightness = 0.0f;
        g_color_contrast = 1.0f;
    } else if (value == "neutral") {
        g_color_mode = "neutral";
        g_red_gain = 1.06f;
        g_green_gain = 1.0f;
        g_blue_gain = 0.94f;
        g_color_brightness = 0.0f;
        g_color_contrast = 1.0f;
    } else if (value == "natural_plus") {
        g_color_mode = "natural_plus";
        g_red_gain = 1.04f;
        g_green_gain = 1.0f;
        g_blue_gain = 0.97f;
        g_color_brightness = 0.015f;
        g_color_contrast = 1.04f;
    } else if (value == "warm") {
        g_color_mode = "warm";
        g_red_gain = 1.12f;
        g_green_gain = 1.0f;
        g_blue_gain = 0.88f;
        g_color_brightness = 0.0f;
        g_color_contrast = 1.0f;
    } else if (value == "cool") {
        g_color_mode = "cool";
        g_red_gain = 0.96f;
        g_green_gain = 1.0f;
        g_blue_gain = 1.05f;
        g_color_brightness = 0.0f;
        g_color_contrast = 1.0f;
    } else if (value == "desk") {
        g_color_mode = "desk";
        g_red_gain = 1.10f;
        g_green_gain = 1.02f;
        g_blue_gain = 0.86f;
        g_color_brightness = 0.0f;
        g_color_contrast = 1.02f;
    } else {
        return JNI_FALSE;
    }
    g_vk.camera_intermediate_ready = false;
    g_gpu_preview.color_mode = g_color_mode;
    g_gpu_preview.red_gain = static_cast<double>(g_red_gain);
    g_gpu_preview.green_gain = static_cast<double>(g_green_gain);
    g_gpu_preview.blue_gain = static_cast<double>(g_blue_gain);
    g_gpu_preview.color_brightness = static_cast<double>(g_color_brightness);
    g_gpu_preview.color_contrast = static_cast<double>(g_color_contrast);
    return JNI_TRUE;
}

std::vector<uint8_t> read_byte_array(JNIEnv *env, jbyteArray array) {
    std::vector<uint8_t> out;
    if (array == nullptr) return out;
    jsize len = env->GetArrayLength(array);
    if (len <= 0) return out;
    out.resize(static_cast<size_t>(len));
    env->GetByteArrayRegion(array, 0, len, reinterpret_cast<jbyte*>(out.data()));
    return out;
}

extern "C" JNIEXPORT void JNICALL
Java_com_luvatrix_app_NativeVulkan_setCameraFrameYuv420(
    JNIEnv *env,
    jobject,
    jstring slotName,
    jbyteArray yPlane,
    jbyteArray uPlane,
    jbyteArray vPlane,
    jint width,
    jint height,
    jint yRowStride,
    jint uRowStride,
    jint vRowStride,
    jint yPixelStride,
    jint uPixelStride,
    jint vPixelStride,
    jlong timestampNs,
    jlong droppedFrames,
    jint rotationDegrees
) {
    std::string slot = "primary";
    if (slotName != nullptr) {
        const char* raw_slot = env->GetStringUTFChars(slotName, nullptr);
        if (raw_slot != nullptr) {
            slot = raw_slot;
            env->ReleaseStringUTFChars(slotName, raw_slot);
        }
    }
    std::vector<uint8_t> y = read_byte_array(env, yPlane);
    std::vector<uint8_t> u = read_byte_array(env, uPlane);
    std::vector<uint8_t> v = read_byte_array(env, vPlane);
    if (width <= 0 || height <= 0 || y.empty() || u.empty() || v.empty()) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_mutex);
    CameraYuvFrame& camera = camera_slot(slot);
    camera.preview_enabled = true;
    camera.width = static_cast<int>(width);
    camera.height = static_cast<int>(height);
    camera.y_row_stride = std::max(1, static_cast<int>(yRowStride));
    camera.u_row_stride = std::max(1, static_cast<int>(uRowStride));
    camera.v_row_stride = std::max(1, static_cast<int>(vRowStride));
    camera.y_pixel_stride = std::max(1, static_cast<int>(yPixelStride));
    camera.u_pixel_stride = std::max(1, static_cast<int>(uPixelStride));
    camera.v_pixel_stride = std::max(1, static_cast<int>(vPixelStride));
    camera.timestamp_ns = static_cast<int64_t>(timestampNs);
    camera.dropped_frames = static_cast<uint64_t>(std::max<jlong>(0, droppedFrames));
    camera.rotation_degrees = static_cast<int>(rotationDegrees);
    camera.y = std::move(y);
    camera.u = std::move(u);
    camera.v = std::move(v);
    camera.has_frame = true;
    camera.frames_received += 1;
}

extern "C" JNIEXPORT void JNICALL
Java_com_luvatrix_app_NativeVulkan_clearCameraFrameSlot(JNIEnv *env, jobject, jstring slotName) {
    std::string slot = "primary";
    if (slotName != nullptr) {
        const char* raw_slot = env->GetStringUTFChars(slotName, nullptr);
        if (raw_slot != nullptr) {
            slot = raw_slot;
            env->ReleaseStringUTFChars(slotName, raw_slot);
        }
    }
    std::lock_guard<std::mutex> lock(g_mutex);
    CameraYuvFrame& camera = camera_slot(slot);
    camera.has_frame = false;
    camera.width = 0;
    camera.height = 0;
    camera.y.clear();
    camera.u.clear();
    camera.v.clear();
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_luvatrix_app_NativeVulkan_setCameraFrameHardwareBuffer(
    JNIEnv *env,
    jobject,
    jstring slotName,
    jobject hardwareBuffer,
    jint width,
    jint height,
    jlong timestampNs,
    jint rotationDegrees
) {
    std::string slot = "primary";
    if (slotName != nullptr) {
        const char* raw_slot = env->GetStringUTFChars(slotName, nullptr);
        if (raw_slot != nullptr) {
            slot = raw_slot;
            env->ReleaseStringUTFChars(slotName, raw_slot);
        }
    }
    if (hardwareBuffer == nullptr || width <= 0 || height <= 0) {
        std::lock_guard<std::mutex> lock(g_mutex);
        CameraHardwareBufferFrame& frame = hardware_slot(slot);
        frame.dropped_frames += 1;
        frame.status = "error";
        frame.last_error = "null or invalid HardwareBuffer";
        return JNI_FALSE;
    }
    AHardwareBuffer* native_buffer = AHardwareBuffer_fromHardwareBuffer(env, hardwareBuffer);
    if (native_buffer == nullptr) {
        std::lock_guard<std::mutex> lock(g_mutex);
        CameraHardwareBufferFrame& frame = hardware_slot(slot);
        frame.dropped_frames += 1;
        frame.status = "error";
        frame.last_error = "AHardwareBuffer_fromHardwareBuffer returned null";
        return JNI_FALSE;
    }
    AHardwareBuffer_acquire(native_buffer);
    bool accepted = false;
    {
        std::lock_guard<std::mutex> lock(g_mutex);
        CameraHardwareBufferFrame& frame = hardware_slot(slot);
        release_hardware_buffer(frame);
        frame.buffer = native_buffer;
        frame.has_frame = true;
        frame.width = static_cast<int>(width);
        frame.height = static_cast<int>(height);
        frame.timestamp_ns = static_cast<int64_t>(timestampNs);
        frame.rotation_degrees = static_cast<int>(rotationDegrees);
        frame.frames_received += 1;
        if (g_vk.android_hardware_buffer_extensions && g_vk.initialized) {
            accepted = true;
            frame.status = "queued";
            frame.last_error.clear();
            g_gpu_preview.status = "fallback";
            g_gpu_preview.width = static_cast<int>(width);
            g_gpu_preview.height = static_cast<int>(height);
            g_gpu_preview.timestamp_ns = static_cast<int64_t>(timestampNs);
            g_gpu_preview.last_error = "AHardwareBuffer queued for render-thread import";
        } else {
            frame.status = "fallback";
            frame.last_error = "required Vulkan AHardwareBuffer extensions are unavailable";
            set_gpu_preview_error(frame.last_error, static_cast<int>(width), static_cast<int>(height), static_cast<int64_t>(timestampNs));
        }
        g_preview_gpu_ready = false;
    }
    return accepted ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT void JNICALL
Java_com_luvatrix_app_NativeVulkan_clearCameraHardwareBufferSlot(JNIEnv *env, jobject, jstring slotName) {
    std::string slot = "primary";
    if (slotName != nullptr) {
        const char* raw_slot = env->GetStringUTFChars(slotName, nullptr);
        if (raw_slot != nullptr) {
            slot = raw_slot;
            env->ReleaseStringUTFChars(slotName, raw_slot);
        }
    }
    std::lock_guard<std::mutex> lock(g_mutex);
    CameraHardwareBufferFrame& frame = hardware_slot(slot);
    release_hardware_buffer(frame);
    frame.has_frame = false;
    frame.width = 0;
    frame.height = 0;
    frame.status = "stopped";
    frame.last_error.clear();
    if (slot == "primary") {
        wait_all_preview_frame_fences(g_vk);
        destroy_imported_camera_preview(g_vk);
    }
    if (!g_hardware_primary.has_frame && !g_hardware_secondary.has_frame) {
        g_preview_gpu_ready = false;
        g_gpu_preview.status = "fallback";
        g_gpu_preview.width = 0;
        g_gpu_preview.height = 0;
        g_gpu_preview.timestamp_ns = 0;
        g_gpu_preview.last_error = "gpu preview stopped";
    }
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_luvatrix_app_NativeVulkan_cameraTelemetryJson(JNIEnv *env, jobject) {
    char buffer[12288];
    {
        std::lock_guard<std::mutex> lock(g_mutex);
        const CameraYuvFrame& primary = g_camera_primary;
        const CameraYuvFrame& secondary = g_camera_secondary;
        const CameraHardwareBufferFrame& primary_hw = g_hardware_primary;
        const CameraHardwareBufferFrame& secondary_hw = g_hardware_secondary;
        const char* renderer = g_preview_gpu_ready
            ? "gpu_private_vulkan"
            : (primary_hw.has_frame ? "fallback_cpu_yuv" : g_preview_renderer);
        std::snprintf(
            buffer,
            sizeof(buffer),
            "{\"preview_enabled\":%s,\"has_frame\":%s,\"width\":%d,\"height\":%d,"
            "\"timestamp_ns\":%lld,\"frames_received\":%llu,\"dropped_frames\":%llu,"
            "\"cover_mode\":\"%s\",\"preview_renderer\":\"%s\",\"preview_gpu_ready\":%s,"
            "\"hardware_buffer_extensions\":%s,\"hardware_slots\":{"
            "\"primary\":{\"status\":\"%s\",\"has_frame\":%s,\"width\":%d,\"height\":%d,\"rotation_degrees\":%d,\"timestamp_ns\":%lld,\"frames_received\":%llu,\"dropped_frames\":%llu,\"last_error\":\"%s\"},"
            "\"secondary\":{\"status\":\"%s\",\"has_frame\":%s,\"width\":%d,\"height\":%d,\"rotation_degrees\":%d,\"timestamp_ns\":%lld,\"frames_received\":%llu,\"dropped_frames\":%llu,\"last_error\":\"%s\"}"
            "},\"gpu_preview\":{\"status\":\"%s\",\"width\":%d,\"height\":%d,\"timestamp_ns\":%lld,"
            "\"imports\":%llu,\"draws\":%llu,\"failures\":%llu,\"import_fps\":%.3f,\"draw_fps\":%.3f,"
            "\"last_draw_ms\":%.3f,\"last_import_ms\":%.3f,\"queue_waits\":%llu,"
            "\"overlay_uploads\":%llu,\"overlay_cache_hits\":%llu,\"imports_on_render_thread\":%llu,"
            "\"import_cache_entries\":%u,\"import_cache_hits\":%llu,\"import_cache_misses\":%llu,"
            "\"import_cache_evictions\":%llu,\"last_import_cache_hit\":%s,"
            "\"intermediate_enabled\":%s,\"intermediate_width\":%d,\"intermediate_height\":%d,"
            "\"intermediate_updates\":%llu,\"intermediate_reuses\":%llu,\"last_intermediate_ms\":%.3f,"
            "\"intermediate_last_timestamp_ns\":%lld,\"intermediate_last_error\":\"%s\","
            "\"downsample_filter\":\"%s\",\"filter_preset\":\"%s\","
            "\"downsample_taps\":%u,\"filter_taps\":%u,\"downsample_strength\":%.3f,"
            "\"luma_smoothing\":%.3f,\"chroma_smoothing\":%.3f,\"edge_preserve\":%.3f,"
            "\"convolution_layers\":%u,\"crop_fit_blend\":%.3f,"
            "\"color_mode\":\"%s\",\"red_gain\":%.3f,\"green_gain\":%.3f,\"blue_gain\":%.3f,"
            "\"color_brightness\":%.3f,\"color_contrast\":%.3f,"
            "\"last_downsample_ms\":%.3f,\"last_filter_ms\":%.3f,\"downsample_last_error\":\"%s\","
            "\"frames_in_flight\":%u,\"current_frame_slot\":%u,\"image_fence_waits\":%llu,"
            "\"frame_fence_waits\":%llu,\"acquired_image_index\":%u,\"sync_mode\":\"%s\","
            "\"last_error\":\"%s\"},\"slots\":{"
            "\"primary\":{\"preview_enabled\":%s,\"has_frame\":%s,\"width\":%d,\"height\":%d,\"rotation_degrees\":%d,\"timestamp_ns\":%lld,\"frames_received\":%llu,\"dropped_frames\":%llu},"
            "\"secondary\":{\"preview_enabled\":%s,\"has_frame\":%s,\"width\":%d,\"height\":%d,\"rotation_degrees\":%d,\"timestamp_ns\":%lld,\"frames_received\":%llu,\"dropped_frames\":%llu}"
            "}}",
            primary.preview_enabled ? "true" : "false",
            primary.has_frame ? "true" : "false",
            primary.width,
            primary.height,
            static_cast<long long>(primary.timestamp_ns),
            static_cast<unsigned long long>(primary.frames_received),
            static_cast<unsigned long long>(primary.dropped_frames),
            primary.cover_mode.c_str(),
            renderer,
            g_preview_gpu_ready ? "true" : "false",
            g_vk.android_hardware_buffer_extensions ? "true" : "false",
            primary_hw.status.c_str(),
            primary_hw.has_frame ? "true" : "false",
            primary_hw.width,
            primary_hw.height,
            primary_hw.rotation_degrees,
            static_cast<long long>(primary_hw.timestamp_ns),
            static_cast<unsigned long long>(primary_hw.frames_received),
            static_cast<unsigned long long>(primary_hw.dropped_frames),
            primary_hw.last_error.c_str(),
            secondary_hw.status.c_str(),
            secondary_hw.has_frame ? "true" : "false",
            secondary_hw.width,
            secondary_hw.height,
            secondary_hw.rotation_degrees,
            static_cast<long long>(secondary_hw.timestamp_ns),
            static_cast<unsigned long long>(secondary_hw.frames_received),
            static_cast<unsigned long long>(secondary_hw.dropped_frames),
            secondary_hw.last_error.c_str(),
            g_gpu_preview.status.c_str(),
            g_gpu_preview.width,
            g_gpu_preview.height,
            static_cast<long long>(g_gpu_preview.timestamp_ns),
            static_cast<unsigned long long>(g_gpu_preview.imports),
            static_cast<unsigned long long>(g_gpu_preview.draws),
            static_cast<unsigned long long>(g_gpu_preview.failures),
            g_gpu_preview.import_fps,
            g_gpu_preview.draw_fps,
            g_gpu_preview.last_draw_ms,
            g_gpu_preview.last_import_ms,
            static_cast<unsigned long long>(g_gpu_preview.queue_waits),
            static_cast<unsigned long long>(g_gpu_preview.overlay_uploads),
            static_cast<unsigned long long>(g_gpu_preview.overlay_cache_hits),
            static_cast<unsigned long long>(g_gpu_preview.imports_on_render_thread),
            g_gpu_preview.import_cache_entries,
            static_cast<unsigned long long>(g_gpu_preview.import_cache_hits),
            static_cast<unsigned long long>(g_gpu_preview.import_cache_misses),
            static_cast<unsigned long long>(g_gpu_preview.import_cache_evictions),
            g_gpu_preview.last_import_cache_hit ? "true" : "false",
            g_gpu_preview.intermediate_enabled ? "true" : "false",
            g_gpu_preview.intermediate_width,
            g_gpu_preview.intermediate_height,
            static_cast<unsigned long long>(g_gpu_preview.intermediate_updates),
            static_cast<unsigned long long>(g_gpu_preview.intermediate_reuses),
            g_gpu_preview.last_intermediate_ms,
            static_cast<long long>(g_gpu_preview.intermediate_last_timestamp_ns),
            g_gpu_preview.intermediate_last_error.c_str(),
            g_gpu_preview.downsample_filter.c_str(),
            g_gpu_preview.filter_preset.c_str(),
            g_gpu_preview.downsample_taps,
            g_gpu_preview.filter_taps,
            g_gpu_preview.downsample_strength,
            g_gpu_preview.luma_smoothing,
            g_gpu_preview.chroma_smoothing,
            g_gpu_preview.edge_preserve,
            g_gpu_preview.convolution_layers,
            g_gpu_preview.crop_fit_blend,
            g_gpu_preview.color_mode.c_str(),
            g_gpu_preview.red_gain,
            g_gpu_preview.green_gain,
            g_gpu_preview.blue_gain,
            g_gpu_preview.color_brightness,
            g_gpu_preview.color_contrast,
            g_gpu_preview.last_downsample_ms,
            g_gpu_preview.last_filter_ms,
            g_gpu_preview.downsample_last_error.c_str(),
            g_gpu_preview.frames_in_flight,
            g_gpu_preview.current_frame_slot,
            static_cast<unsigned long long>(g_gpu_preview.image_fence_waits),
            static_cast<unsigned long long>(g_gpu_preview.frame_fence_waits),
            g_gpu_preview.acquired_image_index,
            g_gpu_preview.sync_mode.c_str(),
            g_gpu_preview.last_error.c_str(),
            primary.preview_enabled ? "true" : "false",
            primary.has_frame ? "true" : "false",
            primary.width,
            primary.height,
            primary.rotation_degrees,
            static_cast<long long>(primary.timestamp_ns),
            static_cast<unsigned long long>(primary.frames_received),
            static_cast<unsigned long long>(primary.dropped_frames),
            secondary.preview_enabled ? "true" : "false",
            secondary.has_frame ? "true" : "false",
            secondary.width,
            secondary.height,
            secondary.rotation_degrees,
            static_cast<long long>(secondary.timestamp_ns),
            static_cast<unsigned long long>(secondary.frames_received),
            static_cast<unsigned long long>(secondary.dropped_frames)
        );
    }
    return env->NewStringUTF(buffer);
}
