package app.gsuss.asistente

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.dp

enum class OrbMood {
    Rest,
    Listen,
    Think,
    Speak,
    Sad,
    Scare,
}

@Composable
fun IlariaOrb(
    modifier: Modifier = Modifier,
    mood: OrbMood = OrbMood.Rest,
    voice: Float = 0f,
    onTickle: () -> Unit = {},
) {
    val infinite = rememberInfiniteTransition(label = "ilaria-orb")
    val breath by infinite.animateFloat(
        initialValue = 0.95f,
        targetValue = 1.05f,
        animationSpec = infiniteRepeatable(
            animation = tween(2500, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "breath",
    )
    val floatY by infinite.animateFloat(
        initialValue = -8f,
        targetValue = 8f,
        animationSpec = infiniteRepeatable(
            animation = tween(3500, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "float",
    )
    val bit by infinite.animateFloat(
        initialValue = 0f,
        targetValue = -14f,
        animationSpec = infiniteRepeatable(
            animation = tween(1600, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "bits",
    )
    val orbit by infinite.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(animation = tween(4200, easing = LinearEasing)),
        label = "orbit",
    )
    val ripple by infinite.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(animation = tween(1100, easing = LinearEasing)),
        label = "ripple",
    )
    val speakPulse by infinite.animateFloat(
        initialValue = 1.04f,
        targetValue = 1.12f,
        animationSpec = infiniteRepeatable(
            animation = tween(850, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "speak",
    )
    var tickles by remember { mutableIntStateOf(0) }
    val tickleScale by animateFloatAsState(
        targetValue = if (tickles % 2 == 0) 1f else 1.14f,
        animationSpec = tween(180),
        label = "tickle",
    )
    val sadDrop by animateFloatAsState(
        targetValue = if (mood == OrbMood.Sad) 10f else 0f,
        animationSpec = tween(400),
        label = "sad",
    )
    val voiceClamped = voice.coerceIn(0f, 1f)
    val colors = when (mood) {
        OrbMood.Think -> listOf(Color(0xFFD4C4F0), Color(0xFFC4D8F0))
        OrbMood.Speak -> listOf(Color(0xFFFFCFE3), Color(0xFFFFE8B0))
        OrbMood.Listen -> listOf(Color(0xFFC4E0E5), Color(0xFFFFCFE3))
        OrbMood.Sad -> listOf(Color(0xFF8AA0B8), Color(0xFF6A7A8C))
        OrbMood.Scare -> listOf(Color(0xFFFFD0C4), Color(0xFFF5B8B0))
        OrbMood.Rest -> listOf(Color(0xFFFFCFE3), Color(0xFFC4E0E5))
    }
    val scale = when (mood) {
        OrbMood.Think -> 1f
        OrbMood.Speak -> speakPulse
        OrbMood.Listen -> 0.88f + voiceClamped * 0.28f
        OrbMood.Scare -> 0.94f
        else -> breath
    } * tickleScale
    Box(
        modifier = modifier.size(168.dp),
        contentAlignment = Alignment.Center,
    ) {
        if (mood == OrbMood.Think || mood == OrbMood.Listen) {
            Box(
                modifier = Modifier
                    .size(158.dp)
                    .rotate(orbit)
                    .border(1.dp, Color(0x8CC4D4F0), CircleShape),
            )
            Box(
                modifier = Modifier
                    .size(132.dp)
                    .rotate(-orbit * 1.4f)
                    .border(1.dp, Color(0x73D4C4F0), CircleShape),
            )
        }
        if (mood == OrbMood.Speak) {
            SpeakRipple(progress = ripple, delay = 0f)
            SpeakRipple(progress = (ripple + 0.35f) % 1f, delay = 0f)
        }
        if (mood == OrbMood.Think) {
            ThinkBit(x = -52f, y = -28f + bit, color = Color(0xFFFFE4EF), size = 8)
            ThinkBit(x = 50f, y = -40f + bit * 0.7f, color = Color(0xFFD4C4F0), size = 6)
            ThinkBit(x = -18f, y = 48f + bit * 0.5f, color = Color(0xFFC4E0E5), size = 8)
        }
        Box(
            modifier = Modifier
                .size(140.dp)
                .offset(y = ((if (mood == OrbMood.Listen) 0f else floatY) + sadDrop).dp)
                .scale(scale)
                .shadow(
                    elevation = 20.dp,
                    shape = CircleShape,
                    ambientColor = colors[0],
                    spotColor = colors[1],
                )
                .background(Brush.linearGradient(colors), CircleShape)
                .clickable {
                    tickles += 1
                    onTickle()
                },
            contentAlignment = Alignment.Center,
        ) {
            Box(
                modifier = Modifier
                    .size(48.dp)
                    .background(
                        Brush.radialGradient(listOf(Color.White.copy(alpha = 0.55f), Color.Transparent)),
                        CircleShape,
                    ),
            )
        }
    }
}

@Composable
private fun SpeakRipple(progress: Float, delay: Float) {
    val t = ((progress + delay) % 1f)
    Box(
        modifier = Modifier
            .size(148.dp)
            .graphicsLayer {
                val grow = 0.92f + t * 0.36f
                scaleX = grow
                scaleY = grow
                alpha = (0.7f * (1f - t)).coerceIn(0f, 0.7f)
            }
            .border(1.5.dp, Color(0x73FFE8B0), CircleShape),
    )
}

@Composable
private fun ThinkBit(x: Float, y: Float, color: Color, size: Int) {
    Box(
        modifier = Modifier
            .offset(x.dp, y.dp)
            .size(size.dp)
            .shadow(6.dp, CircleShape, ambientColor = color, spotColor = color)
            .background(color, CircleShape),
    )
}
